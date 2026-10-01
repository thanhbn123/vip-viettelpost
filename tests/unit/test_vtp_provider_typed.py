"""ViettelPostProvider against the typed ShippingProvider contract (mock HTTP only)."""

import inspect
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.models import Address, Money, ShipmentPackage, ShipmentStatus
from app.domain.models.common import ShippingProviderCode
from app.providers.base.dto import (
    AuthResult,
    CreateShipmentRequest,
    FeeRequest,
    ServiceQuery,
    WebhookRequest,
)
from app.providers.base.provider import ShippingProvider
from app.providers.viettel_post import mapping
from app.providers.viettel_post.events import resolve_timezone
from app.providers.viettel_post.provider import (
    ViettelPostProvider,
    ViettelPostRequestError,
    to_vnd,
)
from app.webhooks.viettel_post_payload import RejectionKind, WebhookRejected
from tests.unit.test_vtp_api import CANCEL_SAMPLE, CREATE_SAMPLE, FEE_SAMPLE, SERVICES_SAMPLE
from tests.unit.vtp_fakes import FAKE_LONG_TOKEN, Recorder, make_auth, make_client, respond

NOW = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
SECRET = "whk-test-secret-not-real"
OPTIONS = {
    "sender_location": {"province_id": 1, "district_id": 12, "ward_id": 49876},
    "receiver_location": {"province_id": 34, "district_id": None, "ward_id": 7393},
}
SENDER = Address(name="Người gửi", phone="0900000000", address_line="1 Đường A", province="Hà Nội")
RECEIVER = Address(
    name="Người nhận",
    phone="0900000001",
    address_line="2 Đường B",
    ward="Phường C",
    province="Bắc Ninh",
)


def provider_with(routes, **kwargs):
    recorder = Recorder(routes)
    client = make_client(recorder)
    provider = ViettelPostProvider(
        client, make_auth(client, static_token=FAKE_LONG_TOKEN), clock=lambda: NOW, **kwargs
    )
    return provider, recorder


def pkg(weight, **kw):
    return ShipmentPackage(weight_grams=weight, **kw)


def create_request(**overrides):
    data = {
        "order_id": "VIP-0001",
        "sender": SENDER,
        "receiver": RECEIVER,
        "packages": [
            pkg(100, length_cm=10, width_cm=20, height_cm=5, declared_value=Money(amount=990000))
        ],
        "service_code": "VHT",
        "cod_amount": Money(amount=562000),
        "provider_options": {**OPTIONS, "order_payment": 3, "product_name": "Hàng thử"},
    }
    data.update(overrides)
    return CreateShipmentRequest(**data)


def test_adapter_implements_typed_contract():
    assert issubclass(ViettelPostProvider, ShippingProvider)
    assert not inspect.isabstract(ViettelPostProvider)
    assert ViettelPostProvider.code is ShippingProviderCode.VIETTEL_POST


@pytest.mark.asyncio
async def test_authenticate_returns_result_without_token():
    provider, recorder = provider_with({})
    result = await provider.authenticate()
    assert result == AuthResult(provider="VIETTEL_POST", authenticated=True, expires_at=None)
    assert FAKE_LONG_TOKEN not in repr(result) + result.model_dump_json()
    assert recorder.requests == []  # static token: no network


@pytest.mark.asyncio
async def test_get_services_maps_ids_total_weight_and_money():
    provider, recorder = provider_with({mapping.GET_SERVICES_PATH: respond(SERVICES_SAMPLE)})
    services = await provider.get_services(
        ServiceQuery(
            sender=SENDER,
            receiver=RECEIVER,
            packages=[pkg(100), pkg(250)],
            provider_options=OPTIONS,
        )
    )
    assert len(services) == 1
    assert services[0].service_code == "PHS"
    assert services[0].name == "Nội tỉnh tiết kiệm"
    assert services[0].estimated_fee == Money(amount=Decimal(26400))
    (body,) = recorder.bodies(mapping.GET_SERVICES_PATH)
    assert body == {
        "SENDER_PROVINCE": 1,
        "SENDER_DISTRICT": 12,
        "SENDER_WARD": 49876,
        "RECEIVER_PROVINCE": 34,
        "RECEIVER_DISTRICT": None,
        "RECEIVER_WARD": 7393,
        "PRODUCT_TYPE": "HH",
        "PRODUCT_WEIGHT": 350,  # total of both packages
        "MONEY_COLLECTION": 0,  # no COD -> 0
        "TYPE": 1,
    }
    # two packages: no combined dimensions, no declared value
    assert "PRODUCT_LENGTH" not in body and "PRODUCT_PRICE" not in body


@pytest.mark.asyncio
async def test_calculate_fee_typed():
    provider, recorder = provider_with({mapping.CALCULATE_FEE_PATH: respond(FEE_SAMPLE)})
    quote = await provider.calculate_fee(
        FeeRequest(
            sender=SENDER,
            receiver=RECEIVER,
            packages=[pkg(100, length_cm=10, width_cm=20, height_cm=5)],
            service_code="VCN",
            cod_amount=Money(amount="562000.00"),
            provider_options={**OPTIONS, "extra_service_codes": "GBP"},
        )
    )
    assert quote.total == Money(amount=Decimal(14700))
    assert quote.service_code == "VCN"
    (body,) = recorder.bodies(mapping.CALCULATE_FEE_PATH)
    assert body["ORDER_SERVICE"] == "VCN"
    assert body["ORDER_SERVICE_ADD"] == "GBP"
    assert body["NATIONAL_TYPE"] == 1
    assert body["MONEY_COLLECTION"] == 562000 and isinstance(body["MONEY_COLLECTION"], int)
    assert (body["PRODUCT_LENGTH"], body["PRODUCT_WIDTH"], body["PRODUCT_HEIGHT"]) == (10, 20, 5)


@pytest.mark.asyncio
async def test_calculate_fee_requires_service_code_before_network():
    provider, recorder = provider_with({})
    with pytest.raises(ViettelPostRequestError):
        await provider.calculate_fee(
            FeeRequest(
                sender=SENDER, receiver=RECEIVER, packages=[pkg(1)], provider_options=OPTIONS
            )
        )
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_create_shipment_typed_mapping():
    provider, recorder = provider_with({mapping.CREATE_ORDER_PATH: respond(CREATE_SAMPLE)})
    result = await provider.create_shipment(create_request())
    assert result.tracking_number == "15878180012"
    assert result.status is ShipmentStatus.CREATED
    assert result.order_id == "VIP-0001"
    assert result.fee == Money(amount=Decimal(16500))
    (body,) = recorder.bodies(mapping.CREATE_ORDER_PATH)
    assert body["ORDER_NUMBER"] == "VIP-0001"
    assert body["ORDER_PAYMENT"] == 3
    assert body["ORDER_SERVICE"] == "VHT"
    assert body["PRODUCT_PRICE"] == 990000
    assert body["MONEY_COLLECTION"] == 562000
    assert body["PRODUCT_NAME"] == "Hàng thử"
    assert body["SENDER_FULLNAME"] == "Người gửi"
    assert body["RECEIVER_ADDRESS"] == "2 Đường B, Phường C, Bắc Ninh"
    assert "LIST_ITEM" not in body


@pytest.mark.asyncio
async def test_create_shipment_items_from_options():
    provider, recorder = provider_with({mapping.CREATE_ORDER_PATH: respond(CREATE_SAMPLE)})
    options = {
        **OPTIONS,
        "order_payment": 1,
        "items": [{"name": "SP", "quantity": 2, "price_vnd": 1000, "weight_grams": 50}],
    }
    await provider.create_shipment(create_request(provider_options=options, cod_amount=None))
    (body,) = recorder.bodies(mapping.CREATE_ORDER_PATH)
    assert body["LIST_ITEM"] == [
        {"PRODUCT_NAME": "SP", "PRODUCT_QUANTITY": 2, "PRODUCT_PRICE": 1000, "PRODUCT_WEIGHT": 50}
    ]


@pytest.mark.parametrize(
    "options",
    [
        {**OPTIONS},  # order_payment missing: no default, owner decision
        {**OPTIONS, "order_payment": 9},
        {"receiver_location": OPTIONS["receiver_location"], "order_payment": 1},
        {**OPTIONS, "order_payment": 1, "unknown": True},
        {
            **OPTIONS,
            "order_payment": 1,
            "sender_location": {"province_id": "1", "district_id": 1, "ward_id": 1},
        },
    ],
)
@pytest.mark.asyncio
async def test_create_shipment_rejects_bad_options_before_network(options):
    provider, recorder = provider_with({})
    with pytest.raises(ViettelPostRequestError):
        await provider.create_shipment(create_request(provider_options=options))
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_create_shipment_rejects_over_long_field_as_request_error():
    provider, recorder = provider_with({})
    long_name = Address(name="x" * 200, phone="0900000000", address_line="a", province="b")
    with pytest.raises(ViettelPostRequestError):
        await provider.create_shipment(create_request(sender=long_name))
    assert recorder.requests == []


def test_money_to_vnd_rules():
    assert to_vnd(Money(amount="1000.00"), "x") == 1000
    assert to_vnd(None, "x") is None
    with pytest.raises(ViettelPostRequestError):
        to_vnd(Money(amount="1000.50"), "x")
    with pytest.raises(ViettelPostRequestError):
        to_vnd(Money(amount=1, currency="USD"), "x")


@pytest.mark.asyncio
async def test_cancel_typed():
    provider, recorder = provider_with({mapping.UPDATE_ORDER_STATUS_PATH: respond(CANCEL_SAMPLE)})
    result = await provider.cancel_shipment(" 301298000044 ")
    assert result.cancelled is True
    assert result.status is ShipmentStatus.CANCELLED
    assert result.tracking_number == "301298000044"


@pytest.mark.asyncio
async def test_get_shipment_not_implemented_without_network():
    provider, recorder = provider_with({})
    with pytest.raises(NotImplementedError):
        await provider.get_shipment("301298000044")
    assert recorder.requests == []


def webhook(status=501, token=SECRET, date="29/09/2026 10:15:00"):
    return WebhookRequest(
        payload={
            "DATA": {
                "ORDER_NUMBER": "301298000044",
                "ORDER_STATUS": status,
                "ORDER_STATUSDATE": date,
                "LOCATION_CURRENTLY": "Bưu cục X",
            },
            "TOKEN": token,
        }
    )


@pytest.mark.asyncio
async def test_handle_webhook_mapped_status_without_timezone_keeps_raw_time():
    provider, _ = provider_with({}, webhook_secret=SECRET)
    result = await provider.handle_webhook(webhook())
    (event,) = result.events
    assert result.accepted is True
    assert event.status is ShipmentStatus.DELIVERED
    assert event.occurred_at is None  # timezone not documented, not configured
    assert event.occurred_at_raw == "29/09/2026 10:15:00"
    assert event.received_at == NOW
    assert event.requires_review is False
    assert event.location == "Bưu cục X"


@pytest.mark.asyncio
async def test_handle_webhook_configured_timezone():
    provider, _ = provider_with(
        {}, webhook_secret=SECRET, webhook_timezone=resolve_timezone("Asia/Ho_Chi_Minh")
    )
    (event,) = (await provider.handle_webhook(webhook())).events
    assert event.occurred_at == datetime(2026, 9, 29, 10, 15, tzinfo=timezone(timedelta(hours=7)))


@pytest.mark.asyncio
async def test_handle_webhook_unknown_status_is_not_guessed():
    provider, _ = provider_with({}, webhook_secret=SECRET)
    (event,) = (await provider.handle_webhook(webhook(status=999))).events
    assert event.status is None
    assert event.provider_status == "999"
    assert event.requires_review is True


@pytest.mark.parametrize("token", ["wrong", "", None])
@pytest.mark.asyncio
async def test_handle_webhook_rejects_bad_token(token):
    provider, _ = provider_with({}, webhook_secret=SECRET)
    with pytest.raises(WebhookRejected) as info:
        await provider.handle_webhook(webhook(token=token))
    assert info.value.kind is RejectionKind.UNAUTHORIZED


@pytest.mark.asyncio
async def test_handle_webhook_fails_closed_without_secret():
    provider, _ = provider_with({})
    with pytest.raises(WebhookRejected) as info:
        await provider.handle_webhook(webhook())
    assert info.value.kind is RejectionKind.NOT_CONFIGURED


def test_resolve_timezone():
    assert resolve_timezone(None) is None
    assert resolve_timezone("") is None
    with pytest.raises(ValueError):
        resolve_timezone("Mars/Base")


@pytest.mark.parametrize("code", [1, 4])
@pytest.mark.asyncio
async def test_cod_with_a_non_collecting_order_payment_is_refused_before_network(code):
    """D-BIZ-001: a COD order must never go out as 'no collection'."""
    provider, recorder = provider_with({})
    options = {**OPTIONS, "order_payment": code}
    with pytest.raises(ViettelPostRequestError, match="D-BIZ-001"):
        await provider.create_shipment(create_request(provider_options=options))
    assert recorder.requests == []


@pytest.mark.parametrize(
    "code,cod",
    [(3, Money(amount=562000)), (2, Money(amount=562000)), (1, None), (1, Money(amount=0))],
)
@pytest.mark.asyncio
async def test_decided_and_consistent_order_payments_are_sent(code, cod):
    provider, recorder = provider_with({mapping.CREATE_ORDER_PATH: respond(CREATE_SAMPLE)})
    options = {**OPTIONS, "order_payment": code}
    await provider.create_shipment(create_request(provider_options=options, cod_amount=cod))
    (body,) = recorder.bodies(mapping.CREATE_ORDER_PATH)
    assert body["ORDER_PAYMENT"] == code
