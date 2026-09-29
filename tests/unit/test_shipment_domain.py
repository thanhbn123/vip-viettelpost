from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.models import (
    Address,
    Money,
    Shipment,
    ShipmentEvent,
    ShipmentPackage,
    ShipmentStatus,
    ShippingProviderCode,
)

ICT = timezone(timedelta(hours=7))

CANONICAL_STATUSES = [
    "DRAFT",
    "READY_TO_CREATE",
    "CREATED",
    "READY_TO_PICK",
    "PICKED",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "DELIVERY_FAILED",
    "RETURNING",
    "RETURNED",
    "CANCELLED",
]


def make_address(**overrides):
    data = {
        "name": "Nguyen Van A",
        "phone": "0900000000",
        "address_line": "1 Duong So 1",
        "province": "Ha Noi",
    }
    data.update(overrides)
    return Address(**data)


def make_event(**overrides):
    data = {
        "provider": ShippingProviderCode.VIETTEL_POST,
        "tracking_number": "TRK-1",
        "status": ShipmentStatus.PICKED,
        "occurred_at": datetime(2026, 9, 29, 10, 0, tzinfo=ICT),
    }
    data.update(overrides)
    return ShipmentEvent(**data)


# --- canonical statuses -----------------------------------------------------


def test_canonical_statuses_exact_set_and_order():
    assert [s.value for s in ShipmentStatus] == CANONICAL_STATUSES
    assert len(ShipmentStatus) == 12


def test_status_values_equal_their_names():
    for status in ShipmentStatus:
        assert status.value == status.name


def test_unknown_status_rejected():
    with pytest.raises(ValueError):
        ShipmentStatus("SOMEWHERE")


# --- shipment creation ------------------------------------------------------


def test_shipment_defaults_to_draft():
    shipment = Shipment(order_id="ORD-1", provider="VIETTEL_POST")
    assert shipment.status is ShipmentStatus.DRAFT
    assert shipment.provider is ShippingProviderCode.VIETTEL_POST
    assert shipment.package_count == 0
    assert shipment.events == []


@pytest.mark.parametrize("order_id", ["", "   "])
def test_empty_order_id_rejected(order_id):
    with pytest.raises(ValidationError):
        Shipment(order_id=order_id, provider="VIETTEL_POST")


def test_order_id_is_stripped():
    assert Shipment(order_id="  ORD-1 ", provider="GHN").order_id == "ORD-1"


def test_invalid_provider_rejected():
    with pytest.raises(ValidationError):
        Shipment(order_id="ORD-1", provider="DHL_UNKNOWN")


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        Shipment(order_id="ORD-1", provider="GHN", status="LOST_IN_SPACE")


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Shipment(order_id="ORD-1", provider="GHN", raw={"x": 1})


def test_assignment_is_validated():
    shipment = Shipment(order_id="ORD-1", provider="GHN")
    with pytest.raises(ValidationError):
        shipment.status = "NOT_A_STATUS"


def test_package_count_and_total_weight():
    shipment = Shipment(
        order_id="ORD-1",
        provider="GHTK",
        packages=[ShipmentPackage(weight_grams=500), ShipmentPackage(weight_grams=1200)],
    )
    assert shipment.package_count == 2
    assert shipment.total_weight_grams == 1700


# --- package validation -----------------------------------------------------


def test_valid_package():
    package = ShipmentPackage(weight_grams=1000, length_cm=30, width_cm=20, height_cm=10)
    assert package.weight_grams == 1000


@pytest.mark.parametrize("weight", [0, -1, -500])
def test_non_positive_weight_rejected(weight):
    with pytest.raises(ValidationError):
        ShipmentPackage(weight_grams=weight)


@pytest.mark.parametrize("weight", [1.5, "1000", True, None])
def test_non_integer_weight_rejected(weight):
    with pytest.raises(ValidationError):
        ShipmentPackage(weight_grams=weight)


@pytest.mark.parametrize("field", ["length_cm", "width_cm", "height_cm"])
@pytest.mark.parametrize("value", [0, -10])
def test_non_positive_dimension_rejected(field, value):
    with pytest.raises(ValidationError):
        ShipmentPackage(weight_grams=100, **{field: value})


def test_package_is_immutable():
    package = ShipmentPackage(weight_grams=100)
    with pytest.raises(ValidationError):
        package.weight_grams = 200


# --- money ------------------------------------------------------------------


def test_money_accepts_int_str_decimal():
    assert Money(amount=30000).amount == Decimal("30000")
    assert Money(amount="30000.50").amount == Decimal("30000.50")
    assert Money(amount=Decimal("1")).currency == "VND"


def test_money_rejects_float():
    with pytest.raises(ValidationError):
        Money(amount=0.1)


def test_money_rejects_negative():
    with pytest.raises(ValidationError):
        Money(amount=-1)


@pytest.mark.parametrize("currency", ["vnd", "VN", "VNDX", ""])
def test_money_rejects_bad_currency(currency):
    with pytest.raises(ValidationError):
        Money(amount=1, currency=currency)


# --- address ----------------------------------------------------------------


@pytest.mark.parametrize("field", ["name", "phone", "address_line", "province"])
def test_address_required_fields_non_empty(field):
    with pytest.raises(ValidationError):
        make_address(**{field: "  "})


# --- events -----------------------------------------------------------------


def test_event_requires_timezone():
    with pytest.raises(ValidationError):
        make_event(occurred_at=datetime(2026, 9, 29, 10, 0))


def test_apply_event_updates_status_and_tracking():
    shipment = Shipment(order_id="ORD-1", provider="VIETTEL_POST")
    event = make_event(provider_status="opaque-code")
    shipment.apply_event(event)
    assert shipment.status is ShipmentStatus.PICKED
    assert shipment.tracking_number == "TRK-1"
    assert shipment.provider_status == "opaque-code"
    assert shipment.events == [event]
    assert shipment.updated_at == event.occurred_at


def test_apply_event_rejects_other_provider():
    shipment = Shipment(order_id="ORD-1", provider="GHN")
    with pytest.raises(ValueError):
        shipment.apply_event(make_event())


def test_apply_event_rejects_other_tracking_number():
    shipment = Shipment(order_id="ORD-1", provider="VIETTEL_POST", tracking_number="TRK-9")
    with pytest.raises(ValueError):
        shipment.apply_event(make_event())
    assert shipment.events == []


# --- serialization ----------------------------------------------------------


def test_shipment_json_round_trip():
    shipment = Shipment(
        order_id="ORD-1",
        provider="VIETTEL_POST",
        sender=make_address(),
        receiver=make_address(name="Tran Thi B", province="Ho Chi Minh"),
        packages=[ShipmentPackage(weight_grams=800, declared_value=Money(amount=250000))],
        cod_amount=Money(amount="250000"),
    )
    shipment.apply_event(make_event())

    data = shipment.model_dump(mode="json")
    assert data["provider"] == "VIETTEL_POST"
    assert data["status"] == "PICKED"
    assert data["cod_amount"] == {"amount": "250000", "currency": "VND"}
    assert data["events"][0]["occurred_at"] == "2026-09-29T10:00:00+07:00"

    restored = Shipment.model_validate_json(shipment.model_dump_json())
    assert restored == shipment


# --- provider events without canonical status (G05) -------------------------


def test_event_without_status_requires_review_and_provider_status():
    with pytest.raises(ValidationError):
        make_event(status=None)
    with pytest.raises(ValidationError):
        make_event(status=None, requires_review=True)  # provider_status missing
    event = make_event(status=None, requires_review=True, provider_status="999")
    assert event.status is None


def test_event_needs_some_time():
    with pytest.raises(ValidationError):
        make_event(occurred_at=None)
    received = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)
    event = make_event(occurred_at=None, occurred_at_raw="29/09/2026 10:00:00", received_at=received)
    assert event.effective_time == received


def test_event_received_at_must_be_aware():
    with pytest.raises(ValidationError):
        make_event(received_at=datetime(2026, 9, 29, 3, 0))


def test_apply_event_without_status_records_but_does_not_move_shipment():
    shipment = Shipment(order_id="ORD-1", provider="VIETTEL_POST", status="IN_TRANSIT")
    event = make_event(status=None, requires_review=True, provider_status="505")
    shipment.apply_event(event)
    assert shipment.status is ShipmentStatus.IN_TRANSIT
    assert shipment.events == [event]
    assert shipment.provider_status is None


@pytest.mark.parametrize("amount", ["1.001", "10000000000000000", "0.123"])
def test_money_rejects_precision_beyond_storage(amount):
    with pytest.raises(ValidationError):
        Money(amount=amount)


def test_money_accepts_two_decimals_and_max():
    assert Money(amount="9999999999999999.99").amount == Decimal("9999999999999999.99")
