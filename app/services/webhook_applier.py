"""Apply durably stored provider webhook events to shipments (CR-SHP-001 G07).

Runs inside the webhook transaction (``SqlWebhookSink(after_store=...)``), so the claim,
the raw event, the shipment update, the appended event and the audit row commit or roll
back together. Provider-neutral: it reads only normalized ``shipping_webhook_events``
columns. A provider may inject ``event_order_key`` to order its events when no
timezone-aware time is available (Viettel Post: ORDER_STATUSDATE text).

Rules (D-026):
* No shipment with that tracking number yet -> row ``IGNORED`` / ``SHIPMENT_NOT_FOUND``;
  ``replay_unmatched`` applies it once the shipment is recorded.
* The event is always appended to ``shipment_events`` (deduplicated by fingerprint).
* An event whose canonical status equals the current one is recorded, nothing else.
* The shipment status changes only when the event has a canonical status, the shipment
  is not in a terminal status (DELIVERED/RETURNED/CANCELLED — the Viettel Post webhook
  page says nothing follows a final status), and the event is not older than the newest
  applied status event. Otherwise the event is kept for review, status unchanged.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Shipment as ShipmentRecord
from app.db.models import ShipmentEvent as ShipmentEventRecord
from app.db.models import ShippingWebhookEvent
from app.domain.models.shipment import ShipmentStatus
from app.repositories.shipping import Actor, ActorType, NewShipmentEvent, ShippingRepository

logger = logging.getLogger("app.services.webhook_applier")

TERMINAL = frozenset(
    {ShipmentStatus.DELIVERED.value, ShipmentStatus.RETURNED.value, ShipmentStatus.CANCELLED.value}
)
NOT_FOUND = "SHIPMENT_NOT_FOUND"
WEBHOOK_ACTOR = Actor(ActorType.WEBHOOK, "provider-webhook")

OrderKey = Callable[[str | None], Any]
"""Maps ``occurred_at_raw`` to a sortable value, or None when it cannot be parsed."""


class WebhookShipmentApplier:
    def __init__(self, *, event_order_key: OrderKey | None = None) -> None:
        self._order_key = event_order_key

    # SqlWebhookSink hook signature
    def __call__(self, session: Session, row: ShippingWebhookEvent, _event: Any) -> None:
        self.apply(session, row)

    def apply(self, session: Session, row: ShippingWebhookEvent) -> str:
        """Apply one stored webhook row. Returns the resulting processing status."""
        repo = ShippingRepository(session)
        shipment = session.scalar(
            select(ShipmentRecord)
            .where(
                ShipmentRecord.provider_id == row.provider_id,
                ShipmentRecord.tracking_number == row.tracking_number,
            )
            .with_for_update()
        )
        now = row.processing_started_at or row.received_at
        if shipment is None:
            row.processing_status = "IGNORED"
            row.error_code = NOT_FOUND
            row.error_message = "no shipment with this tracking number yet"
            row.processed_at = now
            session.flush()
            return row.processing_status

        decision = self._decide(session, shipment, row)
        # Not applied although it had a canonical status -> a human should look at it.
        requires_review = row.requires_review or decision in (
            "AFTER_TERMINAL_STATUS",
            "OUT_OF_ORDER",
        )
        event, created = repo.append_shipment_event(
            shipment,
            NewShipmentEvent(
                canonical_status=row.canonical_status,
                occurred_at=row.occurred_at,
                occurred_at_raw=row.occurred_at_raw,
                received_at=row.received_at,
                provider_status=row.provider_status,
                provider_status_name=row.provider_status_name,
                requires_review=requires_review,
                provider_event_id=row.fingerprint,
                webhook_event_id=row.id,
                metadata={"decision": decision}
                if decision not in ("APPLY", "SAME_STATUS")
                else None,
            ),
        )
        if created and decision == "APPLY":
            before = {"status": shipment.status, "provider_status": shipment.provider_status}
            shipment.status = row.canonical_status
            shipment.provider_status = row.provider_status
            session.flush()
            repo.write_audit_log(
                entity_type="shipment",
                entity_id=str(shipment.id),
                action="STATUS_CHANGED_BY_PROVIDER",
                actor=WEBHOOK_ACTOR,
                before=before,
                after={"status": shipment.status, "provider_status": shipment.provider_status},
                reason=f"webhook_event:{row.id}",
            )
        elif decision not in ("APPLY", "NO_CANONICAL", "SAME_STATUS"):
            logger.warning(
                "webhook event %s for shipment %s not applied: %s", row.id, shipment.id, decision
            )
        row.shipment_id = shipment.id
        row.processing_status = "PROCESSED"
        row.error_code = None if decision in ("APPLY", "NO_CANONICAL", "SAME_STATUS") else decision
        row.error_message = None
        row.processed_at = now
        session.flush()
        return row.processing_status

    def _time_key(self, occurred_at: datetime | None, raw: str | None) -> tuple[int, Any] | None:
        if occurred_at is not None:
            return (0, occurred_at)
        if self._order_key is not None:
            key = self._order_key(raw)
            if key is not None:
                return (1, key)
        return None

    def _decide(self, session: Session, shipment: ShipmentRecord, row: ShippingWebhookEvent) -> str:
        if row.canonical_status is None:
            return "NO_CANONICAL"
        if row.canonical_status == shipment.status:
            return "SAME_STATUS"  # e.g. provider confirming our own cancellation
        if shipment.status in TERMINAL:
            return "AFTER_TERMINAL_STATUS"
        new_key = self._time_key(row.occurred_at, row.occurred_at_raw)
        if new_key is None:
            return "APPLY"
        applied = session.scalars(
            select(ShipmentEventRecord).where(
                ShipmentEventRecord.shipment_id == shipment.id,
                ShipmentEventRecord.canonical_status.is_not(None),
                ShipmentEventRecord.webhook_event_id.is_not(None),
            )
        ).all()
        for previous in applied:
            if (previous.metadata_json or {}).get("decision"):
                continue  # was itself not applied
            old_key = self._time_key(previous.occurred_at, previous.occurred_at_raw)
            if old_key is not None and old_key[0] == new_key[0] and old_key[1] > new_key[1]:
                return "OUT_OF_ORDER"
        return "APPLY"

    def replay_unmatched(self, session: Session, provider_id: int, tracking_number: str) -> int:
        """Apply events that arrived before their shipment was recorded. Returns count."""
        rows = session.scalars(
            select(ShippingWebhookEvent)
            .where(
                ShippingWebhookEvent.provider_id == provider_id,
                ShippingWebhookEvent.tracking_number == tracking_number,
                ShippingWebhookEvent.processing_status.in_(("IGNORED", "RECEIVED")),
            )
            .order_by(ShippingWebhookEvent.received_at, ShippingWebhookEvent.id)
            .with_for_update()
        ).all()
        rows = sorted(
            rows,
            key=lambda r: (
                self._time_key(r.occurred_at, r.occurred_at_raw) or (9, 0),
                r.received_at,
                r.id,
            ),
        )
        applied = 0
        for row in rows:
            if row.processing_status == "IGNORED" and row.error_code != NOT_FOUND:
                continue
            if self.apply(session, row) == "PROCESSED":
                applied += 1
        return applied
