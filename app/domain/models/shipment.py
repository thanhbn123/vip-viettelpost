from dataclasses import dataclass
from enum import StrEnum
from typing import Any

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

@dataclass
class Shipment:
    order_id: str
    provider: str
    tracking_number: str | None = None
    status: ShipmentStatus = ShipmentStatus.DRAFT
    provider_status: str | None = None
    raw: dict[str, Any] | None = None
