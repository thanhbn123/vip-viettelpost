"""Parse and validate the Viettel Post webhook body.

Contract source (verified 2026-09-29): https://partner2.viettelpost.vn/document/webhook

    POST, Content-Type application/json;charset=UTF-8
    {"DATA": {"ORDER_NUMBER": str, "ORDER_STATUS": int, "ORDER_STATUSDATE": "dd/MM/yyyy HH:mm:ss",
              ...}, "TOKEN": str}

Only the fields the pipeline relies on are validated. Everything else in DATA is kept as
received (for audit) and never trusted for decisions.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.providers.viettel_post.status_mapper import normalize_provider_status

VTP_STATUS_DATE_FORMAT = "%d/%m/%Y %H:%M:%S"
MAX_TRACKING_NUMBER_LENGTH = 128


class RejectionKind(StrEnum):
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    MALFORMED_JSON = "MALFORMED_JSON"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_TRACKING_NUMBER = "INVALID_TRACKING_NUMBER"
    INVALID_STATUS_FORMAT = "INVALID_STATUS_FORMAT"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


REJECTION_HTTP_STATUS: dict[RejectionKind, int] = {
    RejectionKind.PAYLOAD_TOO_LARGE: 413,
    RejectionKind.MALFORMED_JSON: 400,
    RejectionKind.INVALID_PAYLOAD: 400,
    RejectionKind.MISSING_FIELD: 400,
    RejectionKind.INVALID_TRACKING_NUMBER: 400,
    RejectionKind.INVALID_STATUS_FORMAT: 400,
    RejectionKind.UNAUTHORIZED: 401,
    RejectionKind.NOT_CONFIGURED: 503,
}


class WebhookRejected(Exception):
    """Request is refused. ``detail`` is safe to return: it never contains payload values."""

    def __init__(self, kind: RejectionKind, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail

    @property
    def http_status(self) -> int:
        return REJECTION_HTTP_STATUS[self.kind]


@dataclass(frozen=True)
class RawVtpEnvelope:
    """Decoded body before field validation. ``token`` is the body-level TOKEN."""

    data: dict[str, Any]
    token: Any


@dataclass(frozen=True)
class VtpWebhookEvent:
    tracking_number: str
    order_reference: str | None
    provider_status: str
    provider_status_raw: Any
    status_date_raw: str | None
    status_date: datetime | None  # naive: the doc does not state a timezone
    data: dict[str, Any]  # DATA object as received; TOKEN is not part of it


def decode_envelope(body: bytes) -> RawVtpEnvelope:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookRejected(RejectionKind.MALFORMED_JSON, "body is not valid JSON") from exc
    return envelope_from_payload(payload)


def envelope_from_payload(payload: Any) -> RawVtpEnvelope:
    """Validate an already-decoded body (a JSON object with DATA and TOKEN)."""
    if not isinstance(payload, dict):
        raise WebhookRejected(RejectionKind.INVALID_PAYLOAD, "body must be a JSON object")
    data = payload.get("DATA")
    if data is None:
        raise WebhookRejected(RejectionKind.MISSING_FIELD, "DATA is required")
    if not isinstance(data, dict):
        raise WebhookRejected(RejectionKind.INVALID_PAYLOAD, "DATA must be a JSON object")
    return RawVtpEnvelope(data=data, token=payload.get("TOKEN"))


def _validate_tracking_number(value: Any) -> str:
    if value is None:
        raise WebhookRejected(RejectionKind.MISSING_FIELD, "DATA.ORDER_NUMBER is required")
    if not isinstance(value, str):
        raise WebhookRejected(
            RejectionKind.INVALID_TRACKING_NUMBER, "DATA.ORDER_NUMBER must be a string"
        )
    tracking = value.strip()
    if not tracking:
        raise WebhookRejected(RejectionKind.MISSING_FIELD, "DATA.ORDER_NUMBER is empty")
    if len(tracking) > MAX_TRACKING_NUMBER_LENGTH:
        raise WebhookRejected(RejectionKind.INVALID_TRACKING_NUMBER, "DATA.ORDER_NUMBER too long")
    # Deny-list, not an allow-list: the doc does not publish the tracking-number alphabet.
    if any(ch.isspace() or not ch.isprintable() for ch in tracking):
        raise WebhookRejected(
            RejectionKind.INVALID_TRACKING_NUMBER,
            "DATA.ORDER_NUMBER contains whitespace or control characters",
        )
    return tracking


def _parse_status_date(value: Any) -> tuple[str | None, datetime | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None
    raw = " ".join(value.split())
    try:
        # Naive on purpose: the official doc does not state the timezone of this field.
        return raw, datetime.strptime(raw, VTP_STATUS_DATE_FORMAT)  # noqa: DTZ007
    except ValueError:
        return raw, None


def parse_event(envelope: RawVtpEnvelope) -> VtpWebhookEvent:
    data = envelope.data
    tracking = _validate_tracking_number(data.get("ORDER_NUMBER"))

    raw_status = data.get("ORDER_STATUS")
    if raw_status is None:
        raise WebhookRejected(RejectionKind.MISSING_FIELD, "DATA.ORDER_STATUS is required")
    provider_status = normalize_provider_status(raw_status)
    if provider_status is None:
        raise WebhookRejected(
            RejectionKind.INVALID_STATUS_FORMAT, "DATA.ORDER_STATUS must be a non-negative integer"
        )

    reference = data.get("ORDER_REFERENCE")
    status_date_raw, status_date = _parse_status_date(data.get("ORDER_STATUSDATE"))
    return VtpWebhookEvent(
        tracking_number=tracking,
        order_reference=(reference.strip() or None) if isinstance(reference, str) else None,
        provider_status=provider_status,
        provider_status_raw=raw_status,
        status_date_raw=status_date_raw,
        status_date=status_date,
        data=data,
    )
