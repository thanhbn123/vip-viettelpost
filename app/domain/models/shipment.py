"""Shipping domain: canonical statuses, packages, events and the shipment entity.

Provider-specific status codes never drive behaviour here. They may be kept
as opaque strings (``provider_status``) for audit only; adapters translate
them into ``ShipmentStatus`` before anything reaches this module.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

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
    """A status observation for a shipment reported by a provider.

    ``status`` is the canonical status when the adapter can map the provider code
    unambiguously. It is ``None`` when the provider code is unknown, or known but
    without an unambiguous canonical equivalent: such an event is still recorded
    (with ``provider_status`` kept verbatim) but it must NOT move the shipment,
    and ``requires_review`` is then always ``True``.

    ``occurred_at`` is the provider's event time, timezone-aware. When the provider
    sends a time without timezone and no timezone is configured for it, the adapter
    leaves ``occurred_at`` empty and keeps the text in ``occurred_at_raw``; the
    gateway never guesses a timezone. ``received_at`` is when the gateway received
    the event. At least one of ``occurred_at`` / ``received_at`` is required.
    """

    provider: ShippingProviderCode
    tracking_number: NonEmptyStr
    status: ShipmentStatus | None = None
    occurred_at: AwareDatetime | None = None
    occurred_at_raw: str | None = None
    received_at: AwareDatetime | None = None
    provider_status: str | None = None
    provider_status_name: str | None = None
    provider_event_id: str | None = None
    requires_review: bool = False
    description: str | None = None
    location: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "ShipmentEvent":
        if self.status is None and not self.requires_review:
            raise ValueError("an event without canonical status must have requires_review=True")
        if self.status is None and not self.provider_status:
            raise ValueError("an event without canonical status must keep provider_status")
        if self.occurred_at is None and self.received_at is None:
            raise ValueError("occurred_at or received_at is required")
        return self

    @property
    def effective_time(self) -> datetime:
        """Best known time of the event: provider time, else gateway receive time."""
        return self.occurred_at or self.received_at  # type: ignore[return-value]


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
        """Record an event; move the shipment only when the event has a canonical status.

        Ordering and transition rules (out-of-order events, terminal statuses) are
        decided by the application layer before calling this method.
        """
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
        if event.status is None:
            return
        self.status = event.status
        self.provider_status = event.provider_status
        self.updated_at = event.effective_time
