from abc import ABC, abstractmethod
from typing import Any

class ShippingProvider(ABC):
    code: str

    @abstractmethod
    async def authenticate(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def get_services(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def calculate_fee(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def create_shipment(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_shipment(self, tracking_number: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def cancel_shipment(self, tracking_number: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def handle_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
