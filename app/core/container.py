from app.core.config import settings
from app.domain.models.common import ShippingProviderCode
from app.providers.viettel_post.client import ViettelPostClient
from app.providers.viettel_post.events import resolve_timezone
from app.providers.viettel_post.provider import ViettelPostProvider
from app.services.shipping_service import ShippingService

_provider = ViettelPostProvider(
    ViettelPostClient(timeout=settings.vtp_timeout_seconds),
    webhook_secret=settings.webhook_shared_secret,
    webhook_timezone=resolve_timezone(settings.vtp_webhook_timezone),
)
_service = ShippingService({ShippingProviderCode.VIETTEL_POST: _provider})


def get_shipping_service() -> ShippingService:
    return _service
