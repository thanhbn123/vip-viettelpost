from app.domain.models.shipment import ShipmentStatus

STATUS_MAP: dict[str, ShipmentStatus] = {
    # TODO: Fill only after verifying official VTP status codes.
}

def map_status(provider_status: str) -> ShipmentStatus:
    return STATUS_MAP.get(provider_status, ShipmentStatus.IN_TRANSIT)
