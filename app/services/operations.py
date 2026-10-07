"""Operational queries over stored shipments (CR-SHP-001 G09). Read-mostly, provider-neutral.

Summaries deliberately omit sender/receiver personal data; the full record stays behind
``GET /shipments/{id}``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Shipment as ShipmentRecord
from app.db.models import ShipmentEvent as EventRecord
from app.db.models import ShippingAuditLog, ShippingProvider, ShippingWebhookEvent
from app.domain.models.common import ShippingProviderCode
from app.domain.models.shipment import ShipmentStatus
from app.repositories.shipping import Actor, ShippingRepository
from app.services.shipping_app import ShipmentNotFoundError

MAX_PAGE = 100
NOTE_ACTION = "OPERATOR_NOTE"


@dataclass(frozen=True)
class ShipmentQuery:
    statuses: Sequence[ShipmentStatus] = ()
    provider: ShippingProviderCode | None = None
    order_id: str | None = None
    tracking_number: str | None = None
    requires_review: bool | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class ShipmentSummary:
    id: int
    order_id: str
    provider: ShippingProviderCode
    status: ShipmentStatus
    tracking_number: str | None
    provider_status: str | None
    requires_review: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Page:
    items: list[ShipmentSummary]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class EventItem:
    id: int
    canonical_status: str | None
    provider_status: str | None
    provider_status_name: str | None
    requires_review: bool
    decision: str | None
    occurred_at: datetime | None
    occurred_at_raw: str | None
    received_at: datetime
    location: str | None
    webhook_event_id: int | None


@dataclass(frozen=True)
class WebhookItem:
    id: int
    processing_status: str
    provider_status: str | None
    canonical_status: str | None
    requires_review: bool
    attempt_count: int
    error_code: str | None
    occurred_at_raw: str | None
    received_at: datetime
    processed_at: datetime | None


@dataclass(frozen=True)
class AuditItem:
    id: int
    action: str
    actor_type: str
    actor_id: str | None
    reason: str | None
    request_id: str | None
    created_at: datetime
    before: object = None
    after: object = None


def _review_flag():
    return exists().where(
        EventRecord.shipment_id == ShipmentRecord.id, EventRecord.requires_review.is_(True)
    )


class ShipmentOperations:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def search(self, query: ShipmentQuery) -> Page:
        limit = max(1, min(query.limit, MAX_PAGE))
        offset = max(0, query.offset)
        review = _review_flag()
        stmt = select(ShipmentRecord, ShippingProvider.code, review.label("needs_review")).join(
            ShippingProvider, ShippingProvider.id == ShipmentRecord.provider_id
        )
        conditions = []
        if query.statuses:
            conditions.append(ShipmentRecord.status.in_([s.value for s in query.statuses]))
        if query.provider is not None:
            conditions.append(ShippingProvider.code == query.provider.value)
        if query.order_id:
            conditions.append(ShipmentRecord.order_id == query.order_id)
        if query.tracking_number:
            conditions.append(ShipmentRecord.tracking_number == query.tracking_number)
        if query.requires_review is not None:
            conditions.append(review if query.requires_review else ~review)
        if query.created_from is not None:
            conditions.append(ShipmentRecord.created_at >= query.created_from)
        if query.created_to is not None:
            conditions.append(ShipmentRecord.created_at < query.created_to)
        stmt = stmt.where(*conditions)
        with self._sessions() as session:
            total = session.scalar(
                select(func.count())
                .select_from(ShipmentRecord)
                .join(ShippingProvider, ShippingProvider.id == ShipmentRecord.provider_id)
                .where(*conditions)
            )
            rows = session.execute(
                stmt.order_by(ShipmentRecord.created_at.desc(), ShipmentRecord.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            items = [
                ShipmentSummary(
                    id=r.id,
                    order_id=r.order_id,
                    provider=ShippingProviderCode(code),
                    status=ShipmentStatus(r.status),
                    tracking_number=r.tracking_number,
                    provider_status=r.provider_status,
                    requires_review=bool(needs_review),
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r, code, needs_review in rows
            ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    def _require(self, session: Session, shipment_id: int) -> ShipmentRecord:
        record = session.get(ShipmentRecord, shipment_id)
        if record is None:
            raise ShipmentNotFoundError(f"shipment {shipment_id} not found")
        return record

    def events(self, shipment_id: int) -> list[EventItem]:
        with self._sessions() as session:
            self._require(session, shipment_id)
            return [
                EventItem(
                    id=e.id,
                    canonical_status=e.canonical_status,
                    provider_status=e.provider_status,
                    provider_status_name=e.provider_status_name,
                    requires_review=e.requires_review,
                    decision=(e.metadata_json or {}).get("decision"),
                    occurred_at=e.occurred_at,
                    occurred_at_raw=e.occurred_at_raw,
                    received_at=e.received_at,
                    location=e.location,
                    webhook_event_id=e.webhook_event_id,
                )
                for e in ShippingRepository(session).list_shipment_events(shipment_id)
            ]

    def webhook_events(self, shipment_id: int) -> list[WebhookItem]:
        """Normalized provider callbacks for a shipment. The raw payload is not exposed."""
        with self._sessions() as session:
            self._require(session, shipment_id)
            rows = session.scalars(
                select(ShippingWebhookEvent)
                .where(ShippingWebhookEvent.shipment_id == shipment_id)
                .order_by(ShippingWebhookEvent.received_at, ShippingWebhookEvent.id)
            )
            return [
                WebhookItem(
                    id=w.id,
                    processing_status=w.processing_status,
                    provider_status=w.provider_status,
                    canonical_status=w.canonical_status,
                    requires_review=w.requires_review,
                    attempt_count=w.attempt_count,
                    error_code=w.error_code,
                    occurred_at_raw=w.occurred_at_raw,
                    received_at=w.received_at,
                    processed_at=w.processed_at,
                )
                for w in rows
            ]

    def audit_trail(self, shipment_id: int) -> list[AuditItem]:
        with self._sessions() as session:
            self._require(session, shipment_id)
            rows = session.scalars(
                select(ShippingAuditLog)
                .where(
                    ShippingAuditLog.entity_type == "shipment",
                    ShippingAuditLog.entity_id == str(shipment_id),
                )
                .order_by(ShippingAuditLog.id)
            )
            return [
                AuditItem(
                    id=a.id,
                    action=a.action,
                    actor_type=a.actor_type,
                    actor_id=a.actor_id,
                    reason=a.reason,
                    request_id=a.request_id,
                    created_at=a.created_at,
                    before=a.before_json,
                    after=a.after_json,
                )
                for a in rows
            ]

    def add_note(
        self, shipment_id: int, text: str, *, actor: Actor, request_id: str | None = None
    ) -> AuditItem:
        """Append an operator note to the shipment's audit trail (no state change)."""
        with self._sessions() as session, session.begin():
            self._require(session, shipment_id)
            log = ShippingRepository(session).write_audit_log(
                entity_type="shipment",
                entity_id=str(shipment_id),
                action=NOTE_ACTION,
                actor=actor,
                reason=text,
                request_id=request_id,
            )
            return AuditItem(
                id=log.id,
                action=log.action,
                actor_type=log.actor_type,
                actor_id=log.actor_id,
                reason=log.reason,
                request_id=log.request_id,
                created_at=log.created_at,
            )
