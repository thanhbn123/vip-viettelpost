"""Re-apply stored webhook events that are not yet attached to a shipment.

Covers events stored as RECEIVED before G07, and events marked IGNORED /
SHIPMENT_NOT_FOUND whose shipment has since been recorded (for example when the webhook
transaction read the shipments table just before the create flow committed the tracking
number). Safe to run repeatedly: each (provider, tracking number) is handled in its own
transaction, events are deduplicated by fingerprint, and rows still without a shipment
stay IGNORED.

Usage (never against production without an approved runbook):
    DATABASE_URL=... python -m app.jobs.replay_webhooks
"""

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ShippingWebhookEvent
from app.services.webhook_applier import NOT_FOUND, WebhookShipmentApplier

logger = logging.getLogger("app.jobs.replay_webhooks")


def replay_pending(sessions: sessionmaker[Session], applier: WebhookShipmentApplier) -> int:
    with sessions() as session:
        keys = session.execute(
            select(ShippingWebhookEvent.provider_id, ShippingWebhookEvent.tracking_number)
            .where(
                ShippingWebhookEvent.tracking_number.is_not(None),
                or_(
                    ShippingWebhookEvent.processing_status == "RECEIVED",
                    (ShippingWebhookEvent.processing_status == "IGNORED")
                    & (ShippingWebhookEvent.error_code == NOT_FOUND),
                ),
            )
            .distinct()
        ).all()
    total = 0
    for provider_id, tracking in keys:
        with sessions() as session, session.begin():
            total += applier.replay_unmatched(session, provider_id, tracking)
    return total


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from app.core.database import get_session_factory
    from app.webhooks.dependencies import get_webhook_applier

    logging.basicConfig(level=logging.INFO)
    count = replay_pending(get_session_factory(), get_webhook_applier())
    logger.info("replayed %s webhook event(s)", count)


if __name__ == "__main__":  # pragma: no cover
    main()
