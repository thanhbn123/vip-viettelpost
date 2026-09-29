"""Provider-neutral shipping application service (CR-SHP-001 G06).

Talks to providers only through ``ShippingProvider`` and to the database only through
``ShippingRepository`` + ``mappers``. No carrier name appears in this module.

Create flow (D-023) — the provider call is never inside a database transaction:

1. Reserve: insert the shipment as READY_TO_CREATE (commit). The partial unique index
   (shp_0003) makes a second active shipment for the same provider+order fail here
   (409), before anything is sent to the carrier.
2. Call the provider.
3. Record the outcome (commit):
   * success            -> CREATED + tracking number + estimated fee, audit.
   * rejected / invalid -> DRAFT (frees the order for a corrected retry), audit.
   * timeout / 5xx /
     unreadable answer  -> stays READY_TO_CREATE, audit PROVIDER_OUTCOME_UNKNOWN. The
                           carrier may have created the order, so the order stays
                           blocked until an operator checks: no blind double creation.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Shipment as ShipmentRecord
from app.domain.models.common import ShippingProviderCode
from app.domain.models.shipment import Shipment, ShipmentStatus
from app.providers.base.dto import (
    CreateShipmentRequest,
    CreateShipmentResult,
    FeeQuote,
    FeeRequest,
)
from app.providers.base.errors import (
    ProviderRejectedError,
    ProviderRequestError,
)
from app.providers.base.provider import ShippingProvider
from app.repositories.mappers import (
    MixedCurrencyError,
    new_shipment_from_request,
    shipment_to_domain,
)
from app.repositories.shipping import Actor, AuditAction, ShippingRepository

logger = logging.getLogger("app.services.shipping_app")

TERMINAL_STATUSES = frozenset(
    {ShipmentStatus.DELIVERED, ShipmentStatus.RETURNED, ShipmentStatus.CANCELLED}
)


class ApplicationError(Exception):
    """Base for errors the API maps to a client-facing code."""

    code = "application_error"


class UnsupportedProviderError(ApplicationError, LookupError):
    code = "provider_not_supported"


class ProviderDisabledError(ApplicationError):
    code = "provider_disabled"


class ShipmentNotFoundError(ApplicationError, LookupError):
    code = "shipment_not_found"


class DuplicateActiveShipmentError(ApplicationError):
    code = "duplicate_active_shipment"


class InvalidShipmentStateError(ApplicationError):
    code = "invalid_shipment_state"


class PersistenceAfterProviderError(ApplicationError):
    """The provider succeeded but recording it failed. Needs an operator."""

    code = "persistence_failed_after_provider_success"


@dataclass(frozen=True)
class ProviderInfo:
    code: ShippingProviderCode
    adapter_available: bool
    enabled: bool


@dataclass(frozen=True)
class StoredShipment:
    id: int
    shipment: Shipment
    created_at: datetime
    requires_review: bool


def _now() -> datetime:
    return datetime.now(UTC)


class ShippingApplication:
    def __init__(
        self,
        providers: Mapping[ShippingProviderCode, ShippingProvider],
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._providers = dict(providers)
        self._sessions = sessions
        self._clock = clock

    # -- providers ------------------------------------------------------------------

    def _adapter(
        self, code: ShippingProviderCode | str
    ) -> tuple[ShippingProviderCode, ShippingProvider]:
        try:
            key = ShippingProviderCode(code)
        except ValueError as exc:
            raise UnsupportedProviderError(f"unsupported provider {code!r}") from exc
        adapter = self._providers.get(key)
        if adapter is None:
            raise UnsupportedProviderError(f"no adapter for provider {key.value}")
        return key, adapter

    def list_providers(self) -> list[ProviderInfo]:
        with self._sessions() as session:
            rows = {p.code: p.enabled for p in ShippingRepository(session).list_providers()}
        return [
            ProviderInfo(
                code=code,
                adapter_available=code in self._providers,
                enabled=bool(rows.get(code.value)) and code in self._providers,
            )
            for code in ShippingProviderCode
        ]

    def _provider_row_id(self, repo: ShippingRepository, code: ShippingProviderCode) -> int:
        row = repo.get_provider_by_code(code.value)
        if row is None or not row.enabled:
            raise ProviderDisabledError(f"provider {code.value} is not enabled")
        return row.id

    # -- quote ----------------------------------------------------------------------

    async def quote(self, provider: ShippingProviderCode | str, request: FeeRequest) -> FeeQuote:
        code, adapter = self._adapter(provider)
        with self._sessions() as session:
            self._provider_row_id(ShippingRepository(session), code)
        return await adapter.calculate_fee(request)

    # -- create ---------------------------------------------------------------------

    async def create_shipment(
        self,
        provider: ShippingProviderCode | str,
        request: CreateShipmentRequest,
        *,
        actor: Actor,
        request_id: str | None = None,
    ) -> StoredShipment:
        code, adapter = self._adapter(provider)
        shipment_id = self._reserve(code, request, actor, request_id)
        try:
            result = await adapter.create_shipment(request)
        except (ProviderRequestError, ProviderRejectedError, MixedCurrencyError) as exc:
            self._record(
                shipment_id,
                actor,
                request_id,
                "PROVIDER_CREATE_REJECTED",
                status=ShipmentStatus.DRAFT,
                reason=type(exc).__name__,
            )
            raise
        except Exception as exc:
            self._record(
                shipment_id,
                actor,
                request_id,
                "PROVIDER_OUTCOME_UNKNOWN",
                status=None,
                reason=type(exc).__name__,
            )
            raise
        try:
            self._record_created(shipment_id, request, result, actor, request_id)
        except Exception as exc:
            # The carrier has the order; our record does not. Loud, with the tracking
            # number (not personal data) so an operator can reconcile.
            logger.error(
                "shipment %s created at provider %s as %s but could not be recorded: %s",
                shipment_id,
                code.value,
                result.tracking_number,
                type(exc).__name__,
            )
            raise PersistenceAfterProviderError(
                f"shipment {shipment_id} was created at the provider as "
                f"{result.tracking_number} but could not be recorded"
            ) from exc
        return self.get_shipment(shipment_id)

    def _reserve(
        self,
        code: ShippingProviderCode,
        request: CreateShipmentRequest,
        actor: Actor,
        request_id: str | None,
    ) -> int:
        with self._sessions() as session:
            try:
                with session.begin():
                    repo = ShippingRepository(session)
                    provider_id = self._provider_row_id(repo, code)
                    new = new_shipment_from_request(
                        request, provider_id=provider_id, status=ShipmentStatus.READY_TO_CREATE
                    )
                    record = repo.create_shipment(new, actor, request_id=request_id)
                    return record.id
            except IntegrityError as exc:
                raise DuplicateActiveShipmentError(
                    f"order {request.order_id} already has an active shipment at {code.value}"
                ) from exc

    def _record(
        self,
        shipment_id: int,
        actor: Actor,
        request_id: str | None,
        action: str,
        *,
        status: ShipmentStatus | None,
        reason: str | None = None,
    ) -> None:
        with self._sessions() as session, session.begin():
            repo = ShippingRepository(session)
            record = repo.get_shipment(shipment_id)
            before = {"status": record.status}
            if status is not None:
                record.status = status.value
            repo.write_audit_log(
                entity_type="shipment",
                entity_id=str(shipment_id),
                action=action,
                actor=actor,
                before=before,
                after={"status": record.status},
                reason=reason,
                request_id=request_id,
            )

    def _record_created(
        self,
        shipment_id: int,
        request: CreateShipmentRequest,
        result: CreateShipmentResult,
        actor: Actor,
        request_id: str | None,
    ) -> None:
        with self._sessions() as session, session.begin():
            repo = ShippingRepository(session)
            record = repo.get_shipment(shipment_id)
            before = {"status": record.status, "tracking_number": record.tracking_number}
            record.status = result.status.value
            record.tracking_number = result.tracking_number
            record.provider_status = result.provider_status
            if result.fee is not None:
                record.estimated_fee = result.fee.amount
            session.flush()
            repo.write_audit_log(
                entity_type="shipment",
                entity_id=str(shipment_id),
                action="PROVIDER_CREATE_SUCCEEDED",
                actor=actor,
                before=before,
                after={"status": record.status, "tracking_number": record.tracking_number},
                request_id=request_id,
            )

    # -- read -----------------------------------------------------------------------

    def _stored(self, repo: ShippingRepository, record: ShipmentRecord) -> StoredShipment:
        events = repo.list_shipment_events(record.id)
        return StoredShipment(
            id=record.id,
            shipment=shipment_to_domain(record, events),
            created_at=record.created_at,
            requires_review=any(e.requires_review for e in events),
        )

    def get_shipment(self, shipment_id: int) -> StoredShipment:
        with self._sessions() as session:
            repo = ShippingRepository(session)
            record = repo.get_shipment(shipment_id)
            if record is None:
                raise ShipmentNotFoundError(f"shipment {shipment_id} not found")
            return self._stored(repo, record)

    def get_by_tracking(
        self, tracking_number: str, provider: ShippingProviderCode | str | None = None
    ) -> StoredShipment:
        with self._sessions() as session:
            repo = ShippingRepository(session)
            query = select(ShipmentRecord).where(ShipmentRecord.tracking_number == tracking_number)
            if provider is not None:
                code, _ = self._adapter(provider)
                row = repo.get_provider_by_code(code.value)
                if row is None:
                    raise ShipmentNotFoundError(f"shipment {tracking_number} not found")
                query = query.where(ShipmentRecord.provider_id == row.id)
            records: Iterable[ShipmentRecord] = session.scalars(query.limit(2)).all()
            records = list(records)
            if not records:
                raise ShipmentNotFoundError(f"shipment {tracking_number} not found")
            if len(records) > 1:
                raise InvalidShipmentStateError(
                    "tracking number exists at several providers; pass the provider"
                )
            return self._stored(repo, records[0])

    # -- cancel ---------------------------------------------------------------------

    async def cancel_shipment(
        self,
        shipment_id: int,
        *,
        actor: Actor,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> StoredShipment:
        with self._sessions() as session:
            record = ShippingRepository(session).get_shipment(shipment_id)
            if record is None:
                raise ShipmentNotFoundError(f"shipment {shipment_id} not found")
            status = ShipmentStatus(record.status)
            tracking = record.tracking_number
            code = ShippingProviderCode(record.provider.code)
        if status in TERMINAL_STATUSES or tracking is None:
            raise InvalidShipmentStateError(
                f"shipment {shipment_id} cannot be cancelled in status {status.value}"
            )
        _, adapter = self._adapter(code)
        try:
            result = await adapter.cancel_shipment(tracking)
        except Exception as exc:
            self._audit_only(
                shipment_id, actor, request_id, "PROVIDER_CANCEL_FAILED", type(exc).__name__
            )
            raise
        with self._sessions() as session, session.begin():
            repo = ShippingRepository(session)
            record = repo.get_shipment(shipment_id)
            before = {"status": record.status}
            record.status = result.status.value
            session.flush()
            repo.write_audit_log(
                entity_type="shipment",
                entity_id=str(shipment_id),
                action=AuditAction.SHIPMENT_CANCELLED,
                actor=actor,
                before=before,
                after={"status": record.status},
                reason=reason,
                request_id=request_id,
            )
        return self.get_shipment(shipment_id)

    def _audit_only(
        self, shipment_id: int, actor: Actor, request_id: str | None, action: str, reason: str
    ) -> None:
        try:
            with self._sessions() as session, session.begin():
                ShippingRepository(session).write_audit_log(
                    entity_type="shipment",
                    entity_id=str(shipment_id),
                    action=action,
                    actor=actor,
                    reason=reason,
                    request_id=request_id,
                )
        except Exception:
            logger.exception("could not audit %s for shipment %s", action, shipment_id)
