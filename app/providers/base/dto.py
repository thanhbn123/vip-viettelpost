"""Typed request/response contracts between the shipping core and provider adapters.

Adapters translate these to and from their carrier's API. Carrier tokens,
URLs and status codes stay inside the adapter.
"""

from typing import Annotated, Any

from pydantic import AwareDatetime, Field

from app.domain.models.common import (
    Address,
    Money,
    NonEmptyStr,
    ShippingProviderCode,
    ValueObject,
)
from app.domain.models.shipment import ShipmentEvent, ShipmentPackage, ShipmentStatus

Packages = Annotated[list[ShipmentPackage], Field(min_length=1)]
"""At least one package: a shipment with zero packages is rejected."""


class AuthResult(ValueObject):
    """Outcome of authenticating with a provider. Never carries the credential."""

    provider: ShippingProviderCode
    authenticated: bool
    expires_at: AwareDatetime | None = None


class ServiceQuery(ValueObject):
    sender: Address
    receiver: Address
    packages: Packages
    cod_amount: Money | None = None


class ServiceOption(ValueObject):
    """A delivery service offered by a provider. ``service_code`` is opaque to the core."""

    provider: ShippingProviderCode
    service_code: NonEmptyStr
    name: NonEmptyStr
    estimated_fee: Money | None = None


class FeeRequest(ValueObject):
    sender: Address
    receiver: Address
    packages: Packages
    service_code: str | None = None
    cod_amount: Money | None = None


class FeeQuote(ValueObject):
    provider: ShippingProviderCode
    total: Money
    service_code: str | None = None


class CreateShipmentRequest(ValueObject):
    order_id: NonEmptyStr
    sender: Address
    receiver: Address
    packages: Packages
    service_code: str | None = None
    cod_amount: Money | None = None
    note: str | None = None
    idempotency_key: str | None = None

    @property
    def package_count(self) -> int:
        return len(self.packages)


class CreateShipmentResult(ValueObject):
    provider: ShippingProviderCode
    order_id: NonEmptyStr
    tracking_number: NonEmptyStr
    status: ShipmentStatus
    provider_status: str | None = None
    fee: Money | None = None


class ShipmentSnapshot(ValueObject):
    """Current state of a shipment as reported by the provider."""

    provider: ShippingProviderCode
    tracking_number: NonEmptyStr
    status: ShipmentStatus
    provider_status: str | None = None
    events: list[ShipmentEvent] = Field(default_factory=list)


class CancelShipmentResult(ValueObject):
    provider: ShippingProviderCode
    tracking_number: NonEmptyStr
    cancelled: bool
    status: ShipmentStatus


class WebhookRequest(ValueObject):
    """Inbound webhook as received. Signature checks happen in the adapter."""

    headers: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any]


class WebhookResult(ValueObject):
    provider: ShippingProviderCode
    accepted: bool
    events: list[ShipmentEvent] = Field(default_factory=list)
