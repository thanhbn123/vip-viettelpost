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


class ShipmentSummaryView(BaseModel):
    """List item: no sender/receiver personal data."""

    id: int
    order_id: str
    provider: ShippingProviderCode
    status: str
    tracking_number: str | None
    provider_status: str | None
    requires_review: bool
    created_at: datetime
    updated_at: datetime


class ShipmentPageView(BaseModel):
    items: list[ShipmentSummaryView]
    total: int
    limit: int
    offset: int


class EventView(BaseModel):
    id: int
    canonical_status: str | None
    provider_status: str | None
    provider_status_name: str | None
    requires_review: bool
    decision: str | None
    occurred_at: datetime | None
    occurred_at_raw: str | None
    received_at: datetime
    location: str | None
    webhook_event_id: int | None


class WebhookEventView(BaseModel):
    id: int
    processing_status: str
    provider_status: str | None
    canonical_status: str | None
    requires_review: bool
    attempt_count: int
    error_code: str | None
    occurred_at_raw: str | None
    received_at: datetime
    processed_at: datetime | None


class AuditView(BaseModel):
    id: int
    action: str
    actor_type: str
    actor_id: str | None
    reason: str | None
    request_id: str | None
    created_at: datetime
    before: object = None
    after: object = None


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
