"""Durable webhook sink on ``shipping_webhook_events`` (replaces the in-memory fakes).

One database transaction per delivery:

1. INSERT the event; the UNIQUE (provider_id, fingerprint) constraint is the atomic claim.
   A concurrent duplicate blocks on that index until the first transaction ends, then
   sees the committed row and is reported as DUPLICATE (never applied twice).
2. An existing row in state FAILED is re-claimed (safe retry); any other existing row is
   a DUPLICATE.
3. ``after_store`` hooks (shipment update, added by G07) run in the same transaction.
4. COMMIT, then the route ACKs with HTTP 200.

If anything fails, the transaction rolls back and the failure is recorded in a SEPARATE
transaction as ``processing_status = FAILED`` with the exception class only (no payload,
no SQL parameters: they may hold personal data). The exception is re-raised so the
route answers 5xx and Viettel Post retries.

The stored payload is the ``DATA`` object only: the body-level ``TOKEN`` is never part
of it, and secret-looking keys are redacted by the repository.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ShippingWebhookEvent
from app.repositories.shipping import ShippingRepository
from app.webhooks.stores import IngestResult, StoredWebhookEvent

logger = logging.getLogger("app.webhooks.sql_sink")

STORED = "RECEIVED"  # stored durably, not yet applied to a shipment
FAILED = "FAILED"
RETRYABLE_STATES = frozenset({FAILED, "PROCESSING"})

AfterStore = Callable[[Session, ShippingWebhookEvent, StoredWebhookEvent], None]


class WebhookProviderNotConfigured(RuntimeError):
    """The provider row is missing (migration shp_0002 not applied?)."""


def _now() -> datetime:
    return datetime.now(UTC)


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
                "provider_status": event.provider_status,
                "provider_status_name": event.provider_status_name,
                "canonical_status": (
                    event.canonical_status.value if event.canonical_status else None
                ),
                "requires_review": event.requires_review,
                "fingerprint_basis": event.fingerprint_basis,
                "occurred_at_raw": event.provider_event_time_raw,
                "occurred_at": self._occurred_at(event),
                "processing_status": "PROCESSING",
                "processing_started_at": now,
            },
        )
        if created:
            result = IngestResult.NEW
        elif row.processing_status in RETRYABLE_STATES:
            result = IngestResult.RETRIED
            row.processing_status = "PROCESSING"
            row.processing_started_at = now
        else:
            return IngestResult.DUPLICATE

        if self._after_store is not None:
            self._after_store(session, row, event)
        if row.processing_status == "PROCESSING":
            repo.mark_webhook_event(row, STORED)
        return result

    def _record_failure(self, event: StoredWebhookEvent, exc: BaseException) -> None:
        code = type(exc).__name__[:64]
        try:
            with self._sessions() as session, session.begin():
                repo = ShippingRepository(session)
                provider = repo.get_provider_by_code(event.provider)
                if provider is None:
                    return
                row, _ = repo.record_webhook_event(
                    provider.id,
                    fingerprint=event.fingerprint,
                    payload=event.raw_data,
                    tracking_number=event.tracking_number,
                    order_id=event.order_reference,
                    normalized={
                        "provider_status": event.provider_status,
                        "requires_review": event.requires_review,
                        "fingerprint_basis": event.fingerprint_basis,
                        "occurred_at_raw": event.provider_event_time_raw,
                        "processing_status": "PROCESSING",
                    },
                )
                repo.mark_webhook_event(
                    row,
                    FAILED,
                    processed_at=self._clock(),
                    error_code=code,
                    error_message="processing failed; see application logs",
                )
        except Exception:
            # Recording the failure is best effort; the original error still propagates
            # and the provider retries. Logged, never swallowed silently.
            logger.exception(
                "could not record webhook failure (fingerprint %s)", event.fingerprint[:16]
            )
