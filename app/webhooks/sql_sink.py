"""Durable webhook sink on ``shipping_webhook_events`` (replaces the in-memory fakes).

One database transaction per delivery:

1. INSERT the event; the UNIQUE (provider_id, fingerprint) constraint is the atomic claim.
   A concurrent duplicate blocks on that index until the first transaction ends, then
   sees the committed row and is reported as DUPLICATE (never applied twice).
2. An existing row is re-claimed only by a conditional
   ``UPDATE ... WHERE processing_status = 'FAILED'``; the row lock makes two concurrent
   retries serialize, and the second one re-checks the state and becomes a DUPLICATE.
   Any other existing row is a DUPLICATE.
3. ``after_store`` hooks (shipment update, added by G07) run in the same transaction.
4. COMMIT, then the route ACKs with HTTP 200.

If anything fails, the transaction rolls back and the failure is recorded in a SEPARATE
transaction as ``processing_status = FAILED`` (never over a row another delivery has
already stored: that update is conditional too) with the exception class only (no payload,
no SQL parameters: they may hold personal data). The exception is re-raised so the
route answers 5xx and Viettel Post retries.

The stored payload is the ``DATA`` object only: the body-level ``TOKEN`` is never part
of it, and secret-looking keys are redacted by the repository.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ShippingWebhookEvent
from app.repositories.shipping import ShippingRepository
from app.webhooks.stores import IngestResult, StoredWebhookEvent

logger = logging.getLogger("app.webhooks.sql_sink")

STORED = "RECEIVED"  # stored durably, not yet applied to a shipment
FAILED = "FAILED"
PROCESSING = "PROCESSING"

AfterStore = Callable[[Session, ShippingWebhookEvent, StoredWebhookEvent], None]


class WebhookProviderNotConfigured(RuntimeError):
    """The provider row is missing (migration shp_0002 not applied?)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _conditional_update(session: Session, row_id: int, from_states: tuple[str, ...], **values):
    """UPDATE one webhook row only if it is still in one of ``from_states``.

    Returns True when the row was updated. On PostgreSQL a concurrent transaction holding
    the row lock makes this wait, then the WHERE clause is re-evaluated on the committed
    version, so a state change by the other transaction is never overwritten.
    """
    result = session.execute(
        update(ShippingWebhookEvent)
        .where(
            ShippingWebhookEvent.id == row_id,
            ShippingWebhookEvent.processing_status.in_(from_states),
        )
        .values(attempt_count=ShippingWebhookEvent.attempt_count + 1, **values)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


class SqlWebhookSink:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        event_timezone: tzinfo | None = None,
        after_store: AfterStore | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._sessions = session_factory
        self._tz = event_timezone
        self._after_store = after_store
        self._clock = clock

    def ingest(self, event: StoredWebhookEvent) -> IngestResult:
        try:
            with self._sessions() as session, session.begin():
                return self._ingest(session, event)
        except Exception as exc:
            self._record_failure(event, exc)
            raise

    def _provider_id(self, repo: ShippingRepository, code: str) -> int:
        provider = repo.get_provider_by_code(code)
        if provider is None:
            raise WebhookProviderNotConfigured(f"shipping provider {code} is not registered")
        return provider.id

    def _occurred_at(self, event: StoredWebhookEvent) -> datetime | None:
        if event.provider_event_time is None or self._tz is None:
            return None
        return event.provider_event_time.replace(tzinfo=self._tz)

    def _normalized(self, event: StoredWebhookEvent) -> dict:
        return {
            "provider_status": event.provider_status,
            "provider_status_name": event.provider_status_name,
            "canonical_status": event.canonical_status.value if event.canonical_status else None,
            "requires_review": event.requires_review,
            "fingerprint_basis": event.fingerprint_basis,
            "occurred_at_raw": event.provider_event_time_raw,
            "occurred_at": self._occurred_at(event),
        }

    def _ingest(self, session: Session, event: StoredWebhookEvent) -> IngestResult:
        repo = ShippingRepository(session)
        provider_id = self._provider_id(repo, event.provider)
        now = self._clock()
        row, created = repo.record_webhook_event(
            provider_id,
            fingerprint=event.fingerprint,
            payload=event.raw_data,
            tracking_number=event.tracking_number,
            order_id=event.order_reference,
            normalized={
                **self._normalized(event),
                "processing_status": PROCESSING,
                "processing_started_at": now,
                "attempt_count": 1,
            },
        )
        if created:
            result = IngestResult.NEW
        else:
            claimed = _conditional_update(
                session,
                row.id,
                (FAILED,),
                processing_status=PROCESSING,
                processing_started_at=now,
                error_code=None,
                error_message=None,
            )
            if not claimed:
                return IngestResult.DUPLICATE
            session.refresh(row)
            result = IngestResult.RETRIED

        if self._after_store is not None:
            self._after_store(session, row, event)
        if row.processing_status == PROCESSING:
            row.processing_status = STORED
            row.processed_at = self._clock()
            session.flush()
        return result

    def _record_failure(self, event: StoredWebhookEvent, exc: BaseException) -> None:
        values = {
            "processing_status": FAILED,
            "processed_at": self._clock(),
            "error_code": type(exc).__name__[:64],
            # Never the exception text: it may carry payload values or SQL parameters.
            "error_message": "processing failed; see application logs",
        }
        try:
            with self._sessions() as session, session.begin():
                repo = ShippingRepository(session)
                provider = repo.get_provider_by_code(event.provider)
                if provider is None:
                    return
                row, created = repo.record_webhook_event(
                    provider.id,
                    fingerprint=event.fingerprint,
                    payload=event.raw_data,
                    tracking_number=event.tracking_number,
                    order_id=event.order_reference,
                    normalized={**self._normalized(event), **values, "attempt_count": 1},
                )
                if not created:
                    # Only a row that is still failed/in flight becomes FAILED; a row a
                    # concurrent delivery has stored successfully is left untouched.
                    _conditional_update(session, row.id, (FAILED, PROCESSING), **values)
        except Exception:
            # Recording the failure is best effort; the original error still propagates
            # and the provider retries. Logged, never swallowed silently.
            logger.exception(
                "could not record webhook failure (fingerprint %s)", event.fingerprint[:16]
            )
