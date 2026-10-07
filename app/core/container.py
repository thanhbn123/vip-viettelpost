from functools import lru_cache

from app.core.config import settings
from app.domain.models.common import ShippingProviderCode
from app.providers.base.provider import ShippingProvider
from app.providers.instrumented import InstrumentedProvider, RetryPolicy
from app.providers.viettel_post.client import ViettelPostClient
from app.providers.viettel_post.events import resolve_timezone
from app.providers.viettel_post.provider import ViettelPostProvider


@lru_cache(maxsize=1)
def get_providers() -> dict[ShippingProviderCode, ShippingProvider]:
    """Registered provider adapters. Built lazily: importing the app opens no connection."""
    retry = RetryPolicy(
        max_attempts=max(1, settings.provider_retry_max_attempts),
        base_delay=settings.provider_retry_base_delay,
        max_delay=settings.provider_retry_max_delay,
    )
    return {
        ShippingProviderCode.VIETTEL_POST: InstrumentedProvider(
            ViettelPostProvider(
                ViettelPostClient(timeout=settings.vtp_timeout_seconds),
                webhook_secret=settings.webhook_shared_secret,
                webhook_timezone=resolve_timezone(settings.vtp_webhook_timezone),
            ),
            retry=retry,
        )
    }
