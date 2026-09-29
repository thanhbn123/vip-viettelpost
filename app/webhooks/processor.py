"""Viettel Post webhook pipeline.

    size check -> decode JSON -> body TOKEN check -> field validation -> fingerprint
    -> idempotency claim -> persist raw event -> map status -> normalized result -> ACK

Authentication: the official page documents a body-level ``TOKEN`` described as a
secret key provided by the partner so the webhook origin can be verified. It is checked
with a constant-time comparison against the configured secret. No HMAC/signature scheme
is documented, so none is implemented. The ``Authorization`` header shown in the doc
sample is not given a verification procedure; it is neither required nor trusted.

HTTP policy (VTP retries up to 5 times until it receives HTTP 200):
    200  valid event (known or unknown status), duplicate/replayed event
    400  malformed JSON / invalid structure / missing or invalid required field
    401  missing or wrong TOKEN
    413  body larger than the configured limit
    503  no webhook secret configured (fail closed)
    5xx  storage failure: the claim is released so the VTP retry is processed
"""

import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.domain.models.shipment import ShipmentStatus
from app.providers.viettel_post.status_mapper import StatusMappingResult, map_status
from app.webhooks.fingerprint import EventFingerprint, build_fingerprint, idempotency_key
from app.webhooks.stores import (
    IdempotencyStore,
    IngestResult,
    InMemoryWebhookSink,
    StoredWebhookEvent,
    WebhookEventStore,
    WebhookSink,
)
from app.webhooks.viettel_post_payload import (
    RejectionKind,
    VtpWebhookEvent,
    WebhookRejected,
    decode_envelope,
    parse_event,
)

logger = logging.getLogger("app.webhooks.viettel_post")

PROVIDER_CODE = "VIETTEL_POST"
DEFAULT_MAX_BODY_BYTES = 64 * 1024


class WebhookResultKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class NormalizedWebhookEvent:
    provider: str
    tracking_number: str
    order_reference: str | None
    provider_status: str
    canonical_status: ShipmentStatus | None
    is_known: bool
    is_terminal: bool
    requires_review: bool
    provider_event_time_raw: str | None
    provider_event_time: datetime | None
    fingerprint: str
    idempotency_key: str


@dataclass(frozen=True)
class WebhookOutcome:
    kind: WebhookResultKind
    http_status: int
    event: NormalizedWebhookEvent | None = None
    rejection: RejectionKind | None = None
    detail: str | None = None

    def response_body(self) -> dict[str, Any]:
        """ACK body. Contains no payload values, PII or secrets."""
        if self.kind is WebhookResultKind.REJECTED:
            return {"result": self.kind.value, "error": self.rejection, "detail": self.detail}
        body: dict[str, Any] = {"result": self.kind.value}
        if self.event is not None:
            body["status_known"] = self.event.is_known
        return body


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WebhookProcessor:
    def __init__(
        self,
        *,
        shared_secret: str | None,
        sink: WebhookSink | None = None,
        idempotency_store: IdempotencyStore | None = None,
        event_store: WebhookEventStore | None = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if sink is None:
            if idempotency_store is None or event_store is None:
                raise ValueError("pass a sink, or both idempotency_store and event_store")
            sink = InMemoryWebhookSink(idempotency_store, event_store)
        self._secret = shared_secret or None
        self._sink = sink
        self._max_body_bytes = max_body_bytes
        self._clock = clock

    @property
    def max_body_bytes(self) -> int:
        return self._max_body_bytes

    def process(self, body: bytes) -> WebhookOutcome:
        try:
            return self._process(body)
        except WebhookRejected as rejected:
            logger.warning("vtp webhook rejected: %s", rejected.kind.value)
            return WebhookOutcome(
                kind=WebhookResultKind.REJECTED,
                http_status=rejected.http_status,
                rejection=rejected.kind,
                detail=rejected.detail,
            )

    def _process(self, body: bytes) -> WebhookOutcome:
        if len(body) > self._max_body_bytes:
            raise WebhookRejected(RejectionKind.PAYLOAD_TOO_LARGE, "body exceeds limit")
        if self._secret is None:
            raise WebhookRejected(RejectionKind.NOT_CONFIGURED, "webhook secret not configured")

        envelope = decode_envelope(body)
        self._verify_token(envelope.token)
        parsed = parse_event(envelope)

        fingerprint = build_fingerprint(
            provider=PROVIDER_CODE,
            tracking_number=parsed.tracking_number,
            provider_status=parsed.provider_status,
            status_date_raw=parsed.status_date_raw,
            data=parsed.data,
        )
        key = idempotency_key(PROVIDER_CODE, fingerprint)
        mapping = map_status(parsed.provider_status)
        event = self._normalized(parsed, mapping, fingerprint, key)

        try:
            result = self._sink.ingest(self._stored(parsed, mapping, fingerprint, key))
        except Exception:
            logger.exception("vtp webhook storage failed; the provider retry will reprocess it")
            raise

        if result is IngestResult.DUPLICATE:
            logger.info(
                "vtp webhook duplicate: status=%s fp=%s",
                mapping.provider_status,
                fingerprint.value[:16],
            )
            return WebhookOutcome(kind=WebhookResultKind.DUPLICATE, http_status=200, event=event)

        if mapping.requires_review:
            logger.warning(
                "vtp webhook needs review: status=%s known=%s fp=%s",
                mapping.provider_status,
                mapping.is_known,
                fingerprint.value[:16],
            )
        else:
            logger.info(
                "vtp webhook accepted: status=%s canonical=%s fp=%s",
                mapping.provider_status,
                mapping.canonical_status,
                fingerprint.value[:16],
            )
        return WebhookOutcome(kind=WebhookResultKind.ACCEPTED, http_status=200, event=event)

    def _verify_token(self, token: Any) -> None:
        assert self._secret is not None
        if not isinstance(token, str) or not token:
            raise WebhookRejected(RejectionKind.UNAUTHORIZED, "TOKEN missing")
        if not hmac.compare_digest(token.encode("utf-8"), self._secret.encode("utf-8")):
            raise WebhookRejected(RejectionKind.UNAUTHORIZED, "TOKEN invalid")

    @staticmethod
    def _normalized(
        parsed: VtpWebhookEvent, mapping: StatusMappingResult, fp: EventFingerprint, key: str
    ) -> NormalizedWebhookEvent:
        return NormalizedWebhookEvent(
            provider=PROVIDER_CODE,
            tracking_number=parsed.tracking_number,
            order_reference=parsed.order_reference,
            provider_status=mapping.provider_status,
            canonical_status=mapping.canonical_status,
            is_known=mapping.is_known,
            is_terminal=mapping.is_terminal,
            requires_review=mapping.requires_review,
            provider_event_time_raw=parsed.status_date_raw,
            provider_event_time=parsed.status_date,
            fingerprint=fp.value,
            idempotency_key=key,
        )

    def _stored(
        self,
        parsed: VtpWebhookEvent,
        mapping: StatusMappingResult,
        fp: EventFingerprint,
        key: str,
    ) -> StoredWebhookEvent:
        return StoredWebhookEvent(
            provider=PROVIDER_CODE,
            idempotency_key=key,
            fingerprint=fp.value,
            fingerprint_basis=fp.basis.value,
            tracking_number=parsed.tracking_number,
            order_reference=parsed.order_reference,
            provider_status=mapping.provider_status,
            provider_status_name=mapping.provider_status_name,
            canonical_status=mapping.canonical_status,
            is_known_status=mapping.is_known,
            is_terminal_status=mapping.is_terminal,
            requires_review=mapping.requires_review,
            provider_event_time_raw=parsed.status_date_raw,
            provider_event_time=parsed.status_date,
            received_at=self._clock(),
            raw_data=parsed.data,
        )
