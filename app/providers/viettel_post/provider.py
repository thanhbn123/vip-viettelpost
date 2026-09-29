from typing import Any
from app.providers.base.provider import ShippingProvider
from app.providers.viettel_post.auth import ViettelPostAuth
from app.providers.viettel_post.client import ViettelPostClient

class ViettelPostProvider(ShippingProvider):
    code = "VIETTEL_POST"

    def __init__(self) -> None:
        self.auth = ViettelPostAuth()
        self.client = ViettelPostClient()

    async def authenticate(self) -> str:
        return await self.auth.get_token()

    async def get_services(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError("Chưa map endpoint dịch vụ Viettel Post.")

    async def calculate_fee(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Chưa map endpoint tính cước Viettel Post.")

    async def create_shipment(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Chưa map endpoint tạo vận đơn Viettel Post.")

    async def get_shipment(self, tracking_number: str) -> dict[str, Any]:
        raise NotImplementedError("Chưa map endpoint tra cứu vận đơn Viettel Post.")

    async def cancel_shipment(self, tracking_number: str) -> dict[str, Any]:
        raise NotImplementedError("Chưa map endpoint hủy vận đơn Viettel Post.")

    async def handle_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"accepted": True, "provider": self.code, "payload": payload}
