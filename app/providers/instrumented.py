"""Provider wrapper: latency logging/metrics and bounded retries for READ-ONLY calls (G11).

Retry policy (D-031):
* Only ``authenticate``, ``get_services``, ``calculate_fee`` and ``get_shipment`` are
  retried - they change nothing at the carrier. ``create_shipment`` and
  ``cancel_shipment`` are NEVER retried automatically: after a timeout the outcome is
  unknown and a blind retry could create or cancel twice (the application layer keeps
  the order blocked instead, D-023).
* Retried errors: ``ProviderTimeoutError`` and ``ProviderUnavailableError`` (network /
  5xx). Rejections, auth failures and bad responses are not retried.
* Bounded: ``max_attempts`` total (default 3), exponential backoff capped at ``max_delay``.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.metrics import metrics
from app.providers.base.dto import (
    AuthResult,
    CancelShipmentResult,
    CreateShipmentRequest,
    CreateShipmentResult,
    FeeQuote,
    FeeRequest,
    ServiceOption,
    ServiceQuery,
    ShipmentSnapshot,
    WebhookRequest,
    WebhookResult,
)
from app.providers.base.errors import ProviderTimeoutError, ProviderUnavailableError
from app.providers.base.provider import ShippingProvider

logger = logging.getLogger("app.providers.calls")
RETRYABLE = (ProviderTimeoutError, ProviderUnavailableError)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 2.0

    def delay(self, attempt: int) -> float:
        return min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))


NO_RETRY = RetryPolicy(max_attempts=1)


class InstrumentedProvider(ShippingProvider):
    def __init__(
        self, inner: ShippingProvider, *, retry: RetryPolicy = NO_RETRY, sleep=asyncio.sleep
    ) -> None:
        self.inner = inner
        self.code = inner.code  # instance attribute mirrors the wrapped adapter
        self._retry = retry
        self._sleep = sleep

    def __getattr__(self, name: str) -> Any:
        # Adapter-specific extras (e.g. ``close``) stay reachable.
        return getattr(self.inner, name)

    async def _call(self, op: str, fn, *args, retryable: bool = False):
        attempts = self._retry.max_attempts if retryable else 1
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            outcome = "ok"
            try:
                return await fn(*args)
            except BaseException as exc:
                outcome = type(exc).__name__
                if attempt < attempts and isinstance(exc, RETRYABLE):
                    delay = self._retry.delay(attempt)
                    logger.warning(
                        "provider_retry provider=%s op=%s attempt=%s/%s error=%s delay_s=%.2f",
                        self.code,
                        op,
                        attempt,
                        attempts,
                        outcome,
                        delay,
                    )
                    metrics.inc("provider_retries", provider=self.code, op=op)
                    await self._sleep(delay)
                    continue
                raise
            finally:
                elapsed = time.perf_counter() - started
                metrics.observe("provider_call_seconds", elapsed, provider=self.code, op=op)
                metrics.inc("provider_calls", provider=self.code, op=op, outcome=outcome)
                logger.info(
                    "provider_call provider=%s op=%s attempt=%s outcome=%s duration_ms=%.1f",
                    self.code,
                    op,
                    attempt,
                    outcome,
                    elapsed * 1000,
                )
        raise AssertionError("unreachable")  # pragma: no cover

    async def authenticate(self) -> AuthResult:
        return await self._call("authenticate", self.inner.authenticate, retryable=True)

    async def get_services(self, query: ServiceQuery) -> list[ServiceOption]:
        return await self._call("get_services", self.inner.get_services, query, retryable=True)

    async def calculate_fee(self, request: FeeRequest) -> FeeQuote:
        return await self._call("calculate_fee", self.inner.calculate_fee, request, retryable=True)

    async def create_shipment(self, request: CreateShipmentRequest) -> CreateShipmentResult:
        return await self._call("create_shipment", self.inner.create_shipment, request)

    async def get_shipment(self, tracking_number: str) -> ShipmentSnapshot:
        return await self._call(
            "get_shipment", self.inner.get_shipment, tracking_number, retryable=True
        )

    async def cancel_shipment(self, tracking_number: str) -> CancelShipmentResult:
        return await self._call("cancel_shipment", self.inner.cancel_shipment, tracking_number)

    async def handle_webhook(self, request: WebhookRequest) -> WebhookResult:
        return await self._call("handle_webhook", self.inner.handle_webhook, request)
