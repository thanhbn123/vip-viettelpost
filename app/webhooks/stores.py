"""Persistence contracts for the webhook pipeline, plus in-memory fakes.

No database exists in this branch. Real implementations belong to the repository
worker; they must keep the same semantics:

- ``IdempotencyStore.claim`` is an atomic set-if-absent (e.g. INSERT with a UNIQUE
  constraint on the key). It returns False when the key already exists.
- ``WebhookEventStore.append`` durably stores one record, or raises.

The in-memory fakes are process-local and lost on restart. They are for tests and local
development only and do not provide idempotency across workers or deploys.
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from app.domain.models.shipment import ShipmentStatus


@dataclass(frozen=True)
class StoredWebhookEvent:
    provider: str
    idempotency_key: str
    fingerprint: str
    fingerprint_basis: str
    tracking_number: str
    order_reference: str | None
    provider_status: str
    provider_status_name: str | None
    canonical_status: ShipmentStatus | None
    is_known_status: bool
    is_terminal_status: bool
    requires_review: bool
    provider_event_time_raw: str | None
    provider_event_time: datetime | None
    received_at: datetime
    raw_data: dict[str, Any]  # DATA object only; the body-level TOKEN is never stored


class IdempotencyStore(Protocol):
    def claim(self, key: str) -> bool: ...

    def release(self, key: str) -> None: ...


class WebhookEventStore(Protocol):
    def append(self, event: StoredWebhookEvent) -> None: ...


class IngestResult(StrEnum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    RETRIED = "RETRIED"  # an earlier delivery of the same event failed; processed again


class WebhookSink(Protocol):
    """Atomically claims and stores one verified webhook event.

    Returns DUPLICATE when the event was already stored successfully. Raises on failure,
    leaving the event claimable again so the provider's retry is processed.
    """

    def ingest(self, event: StoredWebhookEvent) -> IngestResult: ...


class InMemoryWebhookSink:
    """Process-local sink for tests/local dev, built from the two in-memory fakes."""

    def __init__(self, idempotency: IdempotencyStore, events: WebhookEventStore) -> None:
        self.idempotency = idempotency
        self.events = events

    def ingest(self, event: StoredWebhookEvent) -> IngestResult:
        if not self.idempotency.claim(event.idempotency_key):
            return IngestResult.DUPLICATE
        try:
            self.events.append(event)
        except Exception:
            self.idempotency.release(event.idempotency_key)
            raise
        return IngestResult.NEW


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._keys: set[str] = set()
        self._lock = threading.Lock()

    def claim(self, key: str) -> bool:
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._keys.discard(key)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._keys


class InMemoryWebhookEventStore:
    def __init__(self) -> None:
        self._events: list[StoredWebhookEvent] = []
        self._lock = threading.Lock()

    def append(self, event: StoredWebhookEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> list[StoredWebhookEvent]:
        with self._lock:
            return list(self._events)
