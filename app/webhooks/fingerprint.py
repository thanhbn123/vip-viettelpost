"""Deterministic event fingerprint for webhook idempotency.

Viettel Post does not publish an event identifier in the webhook payload
(https://partner2.viettelpost.vn/document/webhook), and states that events may be
duplicated or resent (up to 5 retries until HTTP 200). The fingerprint is therefore
built from the stable fields that identify one status transition:

    provider | ORDER_NUMBER | ORDER_STATUS | ORDER_STATUSDATE

Deliberately excluded (may differ between two deliveries of the same transition):
TOKEN, NOTE, STATUS_NAME, LOCATION_CURRENTLY, MONEY_*, EMPLOYEE_*, POD, REASON_CODE,
receive time.

If ORDER_STATUSDATE is absent, the fingerprint falls back to a canonical hash of the
whole DATA object, so two distinct transitions with the same status are not merged.
"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FingerprintBasis(StrEnum):
    STATUS_TRANSITION = "provider+tracking+status+status_date"
    FULL_DATA = "provider+canonical_data"


@dataclass(frozen=True)
class EventFingerprint:
    value: str
    basis: FingerprintBasis


def _sha256(parts: Any) -> str:
    material = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_fingerprint(
    *,
    provider: str,
    tracking_number: str,
    provider_status: str,
    status_date_raw: str | None,
    data: dict[str, Any],
) -> EventFingerprint:
    if status_date_raw:
        return EventFingerprint(
            value=_sha256([provider, tracking_number, provider_status, status_date_raw]),
            basis=FingerprintBasis.STATUS_TRANSITION,
        )
    return EventFingerprint(
        value=_sha256([provider, data]),
        basis=FingerprintBasis.FULL_DATA,
    )


def idempotency_key(provider: str, fingerprint: EventFingerprint) -> str:
    return f"{provider}:{fingerprint.value}"
