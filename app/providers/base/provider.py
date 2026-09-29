"""The contract every shipping provider adapter implements.

The core talks only to this interface. Each adapter owns its carrier's
auth, endpoints, payload shapes and status-code mapping.
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.domain.models.common import ShippingProviderCode
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


class ShippingProvider(ABC):
    code: ClassVar[ShippingProviderCode]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "code" in cls.__dict__:
            # Raises ValueError for a code not declared in ShippingProviderCode.
            ShippingProviderCode(cls.__dict__["code"])

    @abstractmethod
    async def authenticate(self) -> AuthResult:
        raise NotImplementedError

    @abstractmethod
    async def get_services(self, query: ServiceQuery) -> list[ServiceOption]:
        raise NotImplementedError

    @abstractmethod
    async def calculate_fee(self, request: FeeRequest) -> FeeQuote:
        raise NotImplementedError

    @abstractmethod
    async def create_shipment(self, request: CreateShipmentRequest) -> CreateShipmentResult:
        raise NotImplementedError

    @abstractmethod
    async def get_shipment(self, tracking_number: str) -> ShipmentSnapshot:
        raise NotImplementedError

    @abstractmethod
    async def cancel_shipment(self, tracking_number: str) -> CancelShipmentResult:
        raise NotImplementedError

    @abstractmethod
    async def handle_webhook(self, request: WebhookRequest) -> WebhookResult:
        raise NotImplementedError
