"""Re-apply stored webhook events that are not yet attached to a shipment.

Covers events stored as RECEIVED before G07, FAILED events whose provider retries
were exhausted (e.g. a database outage longer than the retry window), and IGNORED /
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
                    ShippingWebhookEvent.processing_status.in_(("RECEIVED", "FAILED")),
                    (ShippingWebhookEvent.processing_status == "IGNORED")
                    & (ShippingWebhookEvent.error_code == NOT_FOUND),
                ),
            )
            .distinct()
        ).all()
    total = 0
    for provider_id, tracking in keys:
        # One failing key must not abandon the rest of the run (verifier L1, PR #10).
        try:
            with sessions() as session, session.begin():
                total += applier.replay_unmatched(session, provider_id, tracking)
        except Exception:
            logger.exception("replay failed for provider %s tracking %s", provider_id, tracking)
    return total


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from app.core.database import get_session_factory
    from app.webhooks.dependencies import get_webhook_applier

    logging.basicConfig(level=logging.INFO)
    sessions = get_session_factory()
    count = replay_pending(sessions, get_webhook_applier())
    remaining = unmatched_with_shipment(sessions)
    logger.info("replayed %s webhook event(s); unmatched_with_shipment=%s", count, remaining)
    # Non-zero exit lets the scheduler alert when events stay unattached after a run.
    raise SystemExit(0 if remaining == 0 else 3)



def unmatched_with_shipment(sessions: sessionmaker[Session]) -> int:
    """Monitoring gauge (verifier F2/L3 on PR #10): stored events not attached to a
    shipment although the shipment now exists (IGNORED/SHIPMENT_NOT_FOUND, FAILED or
    RECEIVED). Should be 0 after each replay run; > 0 means the job is not running or
    is failing."""
    from sqlalchemy import exists, func

    from app.db.models import Shipment

    with sessions() as session:
        return session.scalar(
            select(func.count())
            .select_from(ShippingWebhookEvent)
            .where(
                or_(
                    ShippingWebhookEvent.processing_status.in_(("RECEIVED", "FAILED")),
                    (ShippingWebhookEvent.processing_status == "IGNORED")
                    & (ShippingWebhookEvent.error_code == NOT_FOUND),
                ),
                exists().where(
                    Shipment.provider_id == ShippingWebhookEvent.provider_id,
                    Shipment.tracking_number == ShippingWebhookEvent.tracking_number,
                ),
            )
        )


if __name__ == "__main__":  # pragma: no cover
    main()
