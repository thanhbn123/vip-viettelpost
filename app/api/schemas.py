"""Typed request/response bodies of the provider-neutral shipping API."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, field_validator

from app.domain.models.common import Money, ShippingProviderCode
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


class FeeLineView(BaseModel):
    id: int
    fee_type: str
    source: str
    amount: Decimal
    currency: str
    note: str | None
    provider_reference: str | None
    created_at: datetime


class ReconciliationView(BaseModel):
    id: int
    kind: str
    statement_reference: str | None
    expected_amount: Decimal
    actual_amount: Decimal
    difference_amount: Decimal
    currency: str
    status: str
    note: str | None
    reconciled_at: datetime | None


class FinanceViewModel(BaseModel):
    shipment_id: int
    currency: str
    cod_expected: Decimal | None
    cod_collected: Decimal | None
    cod_remitted: Decimal | None
    cod_status: str | None
    cod_collected_at: datetime | None
    cod_remitted_at: datetime | None
    remittance_reference: str | None
    estimated_fee: Decimal | None
    actual_fee: Decimal | None
    fees: list[FeeLineView]
    reconciliations: list[ReconciliationView]


Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class CodCollectedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Money
    collected_at: AwareDatetime | None = None


class CodRemittedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Money
    reference: Reference
    remitted_at: AwareDatetime | None = None


class FeeBody(BaseModel):
    """``amount`` may be negative only for ADJUSTMENT (which then requires a note)."""

    model_config = ConfigDict(extra="forbid")

    fee_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    source: Literal["PROVIDER_ACTUAL", "ADJUSTMENT"]
    amount: Decimal
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "VND"
    note: Note | None = None
    provider_reference: Reference | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _no_float(cls, value):
        if isinstance(value, float):
            raise ValueError("amount must not be a float; pass a string or integer")
        return value


class ReconciliationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["COD", "FEE"]
    actual_amount: Money
    statement_reference: Reference | None = None


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note
