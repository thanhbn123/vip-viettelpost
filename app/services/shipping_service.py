from app.providers.base.provider import ShippingProvider

class ShippingService:
    def __init__(self, providers: dict[str, ShippingProvider]) -> None:
        self.providers = providers

    def provider(self, code: str) -> ShippingProvider:
        if code not in self.providers:
            raise ValueError(f"Unsupported shipping provider: {code}")
        return self.providers[code]

    async def create_shipment(self, provider_code: str, payload: dict):
        return await self.provider(provider_code).create_shipment(payload)
