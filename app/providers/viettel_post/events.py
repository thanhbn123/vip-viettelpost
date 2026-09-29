"""Viettel Post webhook event -> provider-neutral ``ShipmentEvent``.

Shared by ``ViettelPostProvider.handle_webhook`` and the durable webhook pipeline so both
produce the same event for the same payload.
"""

from datetime import datetime, tzinfo

from zoneinfo import ZoneInfo

from app.domain.models.common import ShippingProviderCode
from app.domain.models.shipment import ShipmentEvent
from app.providers.viettel_post.status_mapper import StatusMappingResult
from app.webhooks.viettel_post_payload import VtpWebhookEvent


def resolve_timezone(name: str | None) -> tzinfo | None:
    """Timezone configured for ORDER_STATUSDATE, or None (never guessed).

    Raises ``ValueError`` for an unknown IANA name so a typo fails at startup.
    """
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError) as exc:  # ZoneInfoNotFoundError subclasses KeyError
        raise ValueError(f"unknown timezone for Viettel Post webhook: {name!r}") from exc


def zoned_event_time(parsed: VtpWebhookEvent, tz: tzinfo | None) -> datetime | None:
    if parsed.status_date is None or tz is None:
        return None
    return parsed.status_date.replace(tzinfo=tz)


def to_shipment_event(
    parsed: VtpWebhookEvent,
    mapping: StatusMappingResult,
    *,
    received_at: datetime,
    tz: tzinfo | None,
    event_id: str | None = None,
) -> ShipmentEvent:
    location = parsed.data.get("LOCATION_CURRENTLY")
    return ShipmentEvent(
        provider=ShippingProviderCode.VIETTEL_POST,
        tracking_number=parsed.tracking_number,
        status=mapping.canonical_status,
        occurred_at=zoned_event_time(parsed, tz),
        occurred_at_raw=parsed.status_date_raw,
        received_at=received_at,
        provider_status=mapping.provider_status,
        provider_status_name=mapping.provider_status_name,
        # Viettel Post publishes no event id; the caller may pass the idempotency
        # fingerprint so the event is deduplicated downstream as well.
        provider_event_id=event_id,
        requires_review=mapping.requires_review,
        location=location.strip() or None if isinstance(location, str) else None,
    )
