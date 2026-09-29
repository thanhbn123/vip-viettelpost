from app.providers.viettel_post.provider import ViettelPostProvider
from app.services.shipping_service import ShippingService

_provider = ViettelPostProvider()
_service = ShippingService({"VIETTEL_POST": _provider})

def get_shipping_service() -> ShippingService:
    return _service
