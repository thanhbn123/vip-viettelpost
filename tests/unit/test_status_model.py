from app.domain.models.shipment import ShipmentStatus


def test_delivered_status_exists():
    assert ShipmentStatus.DELIVERED.value == "DELIVERED"
