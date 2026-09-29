"""Typed request/response bodies of the provider-neutral shipping API."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.domain.models.common import ShippingProviderCode
from app.domain.models.shipment import Shipment
from app.providers.base.dto import CreateShipmentRequest, FeeRequest


class ProviderView(BaseModel):
    code: ShippingProviderCode
    adapter_available: bool
    enabled: bool


class QuoteBody(FeeRequest):
    provider: ShippingProviderCode


class CreateShipmentBody(CreateShipmentRequest):
    provider: ShippingProviderCode

    def to_request(self) -> CreateShipmentRequest:
        return CreateShipmentRequest.model_validate(self.model_dump(exclude={"provider"}))


class CancelShipmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ShipmentView(Shipment):
    """Stored shipment: the domain shipment plus its gateway id and review flag."""

    id: int
    created_at: datetime
    requires_review: bool


class ErrorBody(BaseModel):
    error: str
    detail: str
    request_id: str | None = None
