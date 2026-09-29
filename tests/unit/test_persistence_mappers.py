"""Domain <-> persistence mapping (G05)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.db.session import make_engine, make_session_factory
from app.domain.models import Address, Money, ShipmentEvent, ShipmentPackage, ShipmentStatus
from app.providers.base.dto import CreateShipmentRequest, CreateShipmentResult
from app.repositories.mappers import (
    MixedCurrencyError,
    new_event_from_domain,
    new_shipment_from_created,
    shipment_to_domain,
    single_currency,
)
from app.repositories.shipping import Actor, ActorType, ShippingRepository

T0 = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)
ADDR = Address(name="A", phone="0900000000", address_line="1 Đường A", province="Hà Nội")


def request(**overrides):
    data = {
        "order_id": "ORD-1",
        "sender": ADDR,
        "receiver": ADDR,
        "packages": [ShipmentPackage(weight_grams=500, declared_value=Money(amount=1000))],
        "service_code": "VHT",
    }
    data.update(overrides)
    return CreateShipmentRequest(**data)


RESULT = CreateShipmentResult(
    provider="VIETTEL_POST",
    order_id="ORD-1",
    tracking_number="VTP1",
    status=ShipmentStatus.CREATED,
    fee=Money(amount=16500),
)


@pytest.fixture
def repo(migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        yield ShippingRepository(session)
    engine.dispose()


def test_single_currency():
    assert single_currency([None, None]) == "VND"
    assert single_currency([Money(amount=1), None]) == "VND"
    with pytest.raises(MixedCurrencyError):
        single_currency([Money(amount=1), Money(amount=1, currency="USD")])


def test_no_cod_maps_to_zero_and_back_to_none(repo):
    provider = repo.get_provider_by_code("VIETTEL_POST")
    new = new_shipment_from_created(request(), RESULT, provider_id=provider.id)
    assert new.cod_amount == Decimal(0)
    record = repo.create_shipment(new, Actor(ActorType.SYSTEM))
    domain = shipment_to_domain(record)
    assert domain.cod_amount is None
    assert domain.fee == Money(amount=Decimal("16500.00"))
    assert domain.status is ShipmentStatus.CREATED
    assert domain.tracking_number == "VTP1"
    assert domain.packages[0].declared_value == Money(amount=Decimal("1000.00"))
    assert domain.receiver == ADDR


def test_cod_round_trip(repo):
    provider = repo.get_provider_by_code("VIETTEL_POST")
    new = new_shipment_from_created(
        request(cod_amount=Money(amount="562000.50")), RESULT, provider_id=provider.id
    )
    record = repo.create_shipment(new, Actor(ActorType.SYSTEM))
    assert shipment_to_domain(record).cod_amount == Money(amount=Decimal("562000.50"))


def test_mixed_currency_shipment_is_rejected():
    with pytest.raises(MixedCurrencyError):
        new_shipment_from_created(
            request(cod_amount=Money(amount=1, currency="USD")), RESULT, provider_id=1
        )


def test_review_event_round_trip(repo):
    provider = repo.get_provider_by_code("VIETTEL_POST")
    record = repo.create_shipment(
        new_shipment_from_created(request(), RESULT, provider_id=provider.id),
        Actor(ActorType.SYSTEM),
    )
    event = ShipmentEvent(
        provider="VIETTEL_POST",
        tracking_number="VTP1",
        status=None,
        requires_review=True,
        provider_status="999",
        occurred_at_raw="29/09/2026 10:00:00",
        received_at=T0,
        provider_event_id="f" * 64,
    )
    stored, created = repo.append_shipment_event(record, new_event_from_domain(event))
    assert created
    domain = shipment_to_domain(record, repo.list_shipment_events(record.id))
    (back,) = domain.events
    assert back.status is None and back.requires_review is True
    assert back.provider_status == "999"
    assert back.occurred_at is None and back.occurred_at_raw == "29/09/2026 10:00:00"
    assert back.received_at == T0


def test_repository_rejects_event_without_status_or_review(repo):
    from app.repositories.shipping import NewShipmentEvent

    provider = repo.get_provider_by_code("VIETTEL_POST")
    record = repo.create_shipment(
        new_shipment_from_created(request(), RESULT, provider_id=provider.id),
        Actor(ActorType.SYSTEM),
    )
    with pytest.raises(ValueError):
        repo.append_shipment_event(record, NewShipmentEvent(None, T0))
