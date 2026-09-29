"""Shipping domain: canonical statuses, packages, events and the shipment entity.

Provider-specific status codes never drive behaviour here. They may be kept
as opaque strings (``provider_status``) for audit only; adapters translate
them into ``ShipmentStatus`` before anything reaches this module.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field

from app.domain.models.common import (
    Address,
    DomainModel,
    Money,
    NonEmptyStr,
    ShippingProviderCode,
    ValueObject,
)

PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class ShipmentStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_TO_CREATE = "READY_TO_CREATE"
    CREATED = "CREATED"
    READY_TO_PICK = "READY_TO_PICK"
    PICKED = "PICKED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    RETURNING = "RETURNING"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ShipmentPackage(ValueObject):
    """One physical parcel. Weight in grams, dimensions in centimetres.

    Integers only (strict): no floats, no booleans, no numeric strings.
    No upper bound is enforced because carrier limits differ; adapters
    reject what their carrier cannot accept.
    """

    weight_grams: PositiveInt
    length_cm: PositiveInt | None = None
    width_cm: PositiveInt | None = None
    height_cm: PositiveInt | None = None
    description: str | None = None
    declared_value: Money | None = None


class ShipmentEvent(ValueObject):
    """A status observation for a shipment, already mapped to canonical status."""

    provider: ShippingProviderCode
    tracking_number: NonEmptyStr
    status: ShipmentStatus
    occurred_at: AwareDatetime
    provider_status: str | None = None
    provider_event_id: str | None = None
    description: str | None = None
    location: str | None = None


class Shipment(DomainModel):
    """A shipment for one VIPORDER order through one provider.

    Status transitions are NOT validated yet: any canonical status may follow
    any other. A transition table is a future enhancement and needs business
    sign-off.
    """

    order_id: NonEmptyStr
    provider: ShippingProviderCode
    status: ShipmentStatus = ShipmentStatus.DRAFT
    tracking_number: str | None = None
    provider_status: str | None = None
    service_code: str | None = None
    sender: Address | None = None
    receiver: Address | None = None
    packages: list[ShipmentPackage] = Field(default_factory=list)
    cod_amount: Money | None = None
    fee: Money | None = None
    events: list[ShipmentEvent] = Field(default_factory=list)
    updated_at: datetime | None = None

    @property
    def package_count(self) -> int:
        return len(self.packages)

    @property
    def total_weight_grams(self) -> int:
        return sum(p.weight_grams for p in self.packages)

    def apply_event(self, event: ShipmentEvent) -> None:
        """Record an event and move the shipment to the event's status."""
        if event.provider != self.provider:
            raise ValueError(
                f"event provider {event.provider} does not match shipment provider {self.provider}"
            )
        if self.tracking_number is None:
            self.tracking_number = event.tracking_number
        elif event.tracking_number != self.tracking_number:
            raise ValueError(
                f"event tracking number {event.tracking_number!r} does not match "
                f"shipment tracking number {self.tracking_number!r}"
            )
        self.events = [*self.events, event]
        self.status = event.status
        self.provider_status = event.provider_status
        self.updated_at = event.occurred_at
