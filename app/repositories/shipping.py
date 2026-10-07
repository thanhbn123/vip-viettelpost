"""Sync repository for the shipping persistence layer.

Returns ORM records (``app.db.models``), not domain models: the typed domain
DTOs live in another worker's branch (W-SHP-01) and are mapped by the service
layer at integration time.

Transaction policy: methods ``flush`` but never ``commit``. The caller owns
the unit of work. Idempotent inserts use a SAVEPOINT so a duplicate does not
roll back the caller's transaction.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    SHIPMENT_STATUSES,
    Shipment,
    ShipmentCod,
    ShipmentEvent,
    ShipmentPackage,
    ShippingAccount,
    ShippingAuditLog,
    ShippingProvider,
    ShippingWebhookEvent,
)
from app.db.types import to_money
from app.repositories.redaction import redact, safe_headers


class AuditAction(StrEnum):
    SHIPMENT_CREATED = "SHIPMENT_CREATED"
    SHIPMENT_CANCELLED = "SHIPMENT_CANCELLED"
    COD_CHANGED = "COD_CHANGED"
    PROVIDER_CHANGED = "PROVIDER_CHANGED"
    ACCOUNT_CHANGED = "ACCOUNT_CHANGED"
    MANUAL_STATUS_OVERRIDE = "MANUAL_STATUS_OVERRIDE"
    RECONCILIATION_ADJUSTED = "RECONCILIATION_ADJUSTED"


class ActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    PROVIDER = "PROVIDER"
    WEBHOOK = "WEBHOOK"


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: str | None = None


@dataclass(frozen=True)
class AddressRecord:
    name: str | None = None
    phone: str | None = None
    address_line: str | None = None
    ward: str | None = None
    district: str | None = None
    province: str | None = None


@dataclass(frozen=True)
class NewPackage:
    weight_grams: int
    length_cm: int | None = None
    width_cm: int | None = None
    height_cm: int | None = None
    description: str | None = None
    declared_value: Decimal | None = None


@dataclass(frozen=True)
class NewShipment:
    order_id: str
    provider_id: int
    shipping_account_id: int | None = None
    tracking_number: str | None = None
    service_code: str | None = None
    status: str = "DRAFT"
    provider_status: str | None = None
    sender: AddressRecord | None = None
    receiver: AddressRecord | None = None
    packages: Sequence[NewPackage] = field(default_factory=tuple)
    cod_amount: Decimal = Decimal(0)
    currency: str = "VND"
    estimated_fee: Decimal | None = None


@dataclass(frozen=True)
class NewShipmentEvent:
    """``canonical_status`` is None for an unknown/unmapped provider status; such an
    event must have ``requires_review=True``. ``occurred_at`` is None when the provider
    time has no known timezone (``occurred_at_raw`` keeps the text)."""

    canonical_status: str | None
    occurred_at: datetime | None
    provider_status: str | None = None
    provider_status_name: str | None = None
    requires_review: bool = False
    occurred_at_raw: str | None = None
    received_at: datetime | None = None
    provider_event_id: str | None = None
    description: str | None = None
    location: str | None = None
    webhook_event_id: int | None = None
    metadata: Mapping[str, Any] | None = None


class ShippingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- providers / accounts -------------------------------------------------

    def create_provider(self, code: str, name: str, enabled: bool = True) -> ShippingProvider:
        provider = ShippingProvider(code=code, name=name, enabled=enabled)
        self.session.add(provider)
        self.session.flush()
        return provider

    def get_provider_by_code(self, code: str) -> ShippingProvider | None:
        return self.session.scalar(select(ShippingProvider).where(ShippingProvider.code == code))

    def create_account(
        self,
        provider_id: int,
        account_name: str,
        *,
        secret_reference: str | None = None,
        external_account_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        enabled: bool = True,
    ) -> ShippingAccount:
        """``secret_reference`` is a pointer (``env://VTP_TOKEN``, ``vault://...``),
        never the secret itself. The DB enforces the ``scheme://`` shape."""
        account = ShippingAccount(
            provider_id=provider_id,
            account_name=account_name,
            external_account_id=external_account_id,
            secret_reference=secret_reference,
            metadata_json=redact(dict(metadata)) if metadata is not None else None,
            enabled=enabled,
        )
        self.session.add(account)
        self.session.flush()
        return account

    # -- shipments --------------------------------------------------------------

    def list_providers(self) -> list[ShippingProvider]:
        return list(self.session.scalars(select(ShippingProvider).order_by(ShippingProvider.code)))

    def create_shipment(
        self, data: NewShipment, actor: Actor, *, request_id: str | None = None
    ) -> Shipment:
        """Insert shipment + packages (+ COD row if COD > 0) + audit, one flush."""
        cod_amount = to_money(data.cod_amount)
        shipment = Shipment(
            order_id=data.order_id,
            provider_id=data.provider_id,
            shipping_account_id=data.shipping_account_id,
            tracking_number=data.tracking_number,
            service_code=data.service_code,
            status=data.status,
            provider_status=data.provider_status,
            package_count=len(data.packages),
            cod_amount=cod_amount,
            currency=data.currency,
            estimated_fee=data.estimated_fee,
            created_by=actor.id,
            **_address_columns("sender", data.sender),
            **_address_columns("receiver", data.receiver),
        )
        shipment.packages = [
            ShipmentPackage(
                package_index=index,
                weight_grams=p.weight_grams,
                length_cm=p.length_cm,
                width_cm=p.width_cm,
                height_cm=p.height_cm,
                description=p.description,
                declared_value=p.declared_value,
            )
            for index, p in enumerate(data.packages, start=1)
        ]
        self.session.add(shipment)
        self.session.flush()

        if cod_amount > 0:
            self.session.add(
                ShipmentCod(
                    shipment_id=shipment.id,
                    expected_amount=cod_amount,
                    currency=data.currency,
                )
            )
        self.write_audit_log(
            entity_type="shipment",
            entity_id=str(shipment.id),
            action=AuditAction.SHIPMENT_CREATED,
            actor=actor,
            after=_shipment_snapshot(shipment),
            request_id=request_id,
        )
        self.session.flush()
        return shipment

    def get_shipment(self, shipment_id: int) -> Shipment | None:
        return self.session.get(Shipment, shipment_id)

    def get_shipment_by_tracking(self, provider_id: int, tracking_number: str) -> Shipment | None:
        return self.session.scalar(
            select(Shipment).where(
                Shipment.provider_id == provider_id,
                Shipment.tracking_number == tracking_number,
            )
        )

    # -- events -----------------------------------------------------------------

    def append_shipment_event(
        self, shipment: Shipment, data: NewShipmentEvent
    ) -> tuple[ShipmentEvent, bool]:
        """Append one history row. Never updates existing rows.

        Returns ``(event, created)``. If ``provider_event_id`` was already
        stored for this provider, the existing row is returned with
        ``created=False``. Updating ``shipments.status`` is the service
        layer's decision (ordering / transition rules), not done here.
        """
        if data.canonical_status is None:
            if not data.requires_review:
                raise ValueError("an event without canonical status must require review")
            if not data.provider_status:
                raise ValueError("an event without canonical status must keep provider_status")
        elif data.canonical_status not in SHIPMENT_STATUSES:
            raise ValueError(f"unknown canonical status: {data.canonical_status}")
        if data.provider_event_id is not None:
            existing = self.session.scalar(
                select(ShipmentEvent).where(
                    ShipmentEvent.provider_id == shipment.provider_id,
                    ShipmentEvent.provider_event_id == data.provider_event_id,
                )
            )
            if existing is not None:
                return existing, False

        event = ShipmentEvent(
            shipment_id=shipment.id,
            provider_id=shipment.provider_id,
            canonical_status=data.canonical_status,
            requires_review=data.requires_review,
            provider_status=data.provider_status,
            provider_status_name=data.provider_status_name,
            provider_event_id=data.provider_event_id,
            description=data.description,
            location=data.location,
            occurred_at=data.occurred_at,
            occurred_at_raw=data.occurred_at_raw,
            **({"received_at": data.received_at} if data.received_at is not None else {}),
            webhook_event_id=data.webhook_event_id,
            metadata_json=redact(dict(data.metadata)) if data.metadata is not None else None,
        )
        try:
            with self.session.begin_nested():
                self.session.add(event)
        except IntegrityError:
            if data.provider_event_id is None:
                raise
            existing = self.session.scalar(
                select(ShipmentEvent).where(
                    ShipmentEvent.provider_id == shipment.provider_id,
                    ShipmentEvent.provider_event_id == data.provider_event_id,
                )
            )
            if existing is None:
                raise
            return existing, False
        return event, True

    def list_shipment_events(self, shipment_id: int) -> list[ShipmentEvent]:
        return list(
            self.session.scalars(
                select(ShipmentEvent)
                .where(ShipmentEvent.shipment_id == shipment_id)
                # Events without a zoned provider time sort by gateway receive time.
                .order_by(
                    func.coalesce(ShipmentEvent.occurred_at, ShipmentEvent.received_at),
                    ShipmentEvent.id,
                )
            )
        )

    # -- webhooks ---------------------------------------------------------------

    def find_webhook_event(
        self, provider_id: int, *, fingerprint: str, event_id: str | None = None
    ) -> ShippingWebhookEvent | None:
        """Idempotency check: match on fingerprint, or on event_id when given."""
        match = ShippingWebhookEvent.fingerprint == fingerprint
        if event_id is not None:
            match = or_(match, ShippingWebhookEvent.event_id == event_id)
        return self.session.scalar(
            select(ShippingWebhookEvent)
            .where(ShippingWebhookEvent.provider_id == provider_id, match)
            .order_by(ShippingWebhookEvent.id)
            .limit(1)
        )

    def record_webhook_event(
        self,
        provider_id: int,
        *,
        fingerprint: str,
        payload: Any,
        event_id: str | None = None,
        tracking_number: str | None = None,
        order_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        normalized: Mapping[str, Any] | None = None,
    ) -> tuple[ShippingWebhookEvent, bool]:
        """Store a raw webhook once. Returns ``(row, created)``.

        ``fingerprint`` is a SHA-256 hex digest computed by the caller over the
        raw request. Payload keys that look secret are redacted; headers are
        kept only if allowlisted.
        """
        existing = self.find_webhook_event(provider_id, fingerprint=fingerprint, event_id=event_id)
        if existing is not None:
            return existing, False

        row = ShippingWebhookEvent(
            provider_id=provider_id,
            event_id=event_id,
            fingerprint=fingerprint,
            tracking_number=tracking_number,
            order_id=order_id,
            payload_json=redact(payload),
            headers_json=safe_headers(headers),
            **_webhook_normalized_columns(normalized),
        )
        try:
            with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError:
            # Lost a race with a concurrent insert of the same event.
            existing = self.find_webhook_event(
                provider_id, fingerprint=fingerprint, event_id=event_id
            )
            if existing is None:
                raise
            return existing, False
        return row, True

    def mark_webhook_event(
        self,
        webhook: ShippingWebhookEvent,
        processing_status: str,
        *,
        processed_at: datetime | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        shipment_id: int | None = None,
    ) -> ShippingWebhookEvent:
        webhook.processing_status = processing_status
        if shipment_id is not None:
            webhook.shipment_id = shipment_id
        webhook.processed_at = processed_at
        webhook.error_code = error_code
        webhook.error_message = error_message
        webhook.attempt_count = webhook.attempt_count + 1
        self.session.flush()
        return webhook

    # -- audit --------------------------------------------------------------------

    def write_audit_log(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: AuditAction | str,
        actor: Actor,
        before: Any = None,
        after: Any = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> ShippingAuditLog:
        log = ShippingAuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=str(action),
            actor_type=str(actor.type),
            actor_id=actor.id,
            before_json=redact(before),
            after_json=redact(after),
            reason=reason,
            request_id=request_id,
        )
        self.session.add(log)
        self.session.flush()
        return log


WEBHOOK_NORMALIZED_COLUMNS = frozenset(
    {
        "provider_status",
        "provider_status_name",
        "canonical_status",
        "requires_review",
        "fingerprint_basis",
        "occurred_at_raw",
        "occurred_at",
        "processing_status",
        "processing_started_at",
        "processed_at",
        "attempt_count",
        "error_code",
        "error_message",
    }
)


def _webhook_normalized_columns(normalized: Mapping[str, Any] | None) -> dict[str, Any]:
    if not normalized:
        return {}
    unknown = set(normalized) - WEBHOOK_NORMALIZED_COLUMNS
    if unknown:
        raise ValueError(f"unsupported webhook columns: {sorted(unknown)}")
    return dict(normalized)


def _address_columns(prefix: str, address: AddressRecord | None) -> dict[str, str | None]:
    address = address or AddressRecord()
    return {
        f"{prefix}_{name}": getattr(address, name)
        for name in ("name", "phone", "address_line", "ward", "district", "province")
    }


def _shipment_snapshot(shipment: Shipment) -> dict[str, Any]:
    return {
        "order_id": shipment.order_id,
        "provider_id": shipment.provider_id,
        "shipping_account_id": shipment.shipping_account_id,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "package_count": shipment.package_count,
        "cod_amount": str(shipment.cod_amount),
        "currency": shipment.currency,
    }
