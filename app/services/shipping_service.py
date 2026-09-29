from app.domain.models.common import ShippingProviderCode
from app.providers.base.dto import CreateShipmentRequest, CreateShipmentResult
from app.providers.base.provider import ShippingProvider


class UnsupportedProviderError(LookupError):
    """No adapter is registered for the requested provider code."""


class ShippingService:
    def __init__(self, providers: dict[ShippingProviderCode, ShippingProvider]) -> None:
        self.providers = dict(providers)

    def provider(self, code: ShippingProviderCode | str) -> ShippingProvider:
        try:
            key = ShippingProviderCode(code)
        except ValueError as exc:
            raise UnsupportedProviderError(f"Unsupported shipping provider: {code}") from exc
        if key not in self.providers:
            raise UnsupportedProviderError(f"Unsupported shipping provider: {code}")
        return self.providers[key]

    async def create_shipment(
        self, provider_code: ShippingProviderCode | str, request: CreateShipmentRequest
    ) -> CreateShipmentResult:
        return await self.provider(provider_code).create_shipment(request)
