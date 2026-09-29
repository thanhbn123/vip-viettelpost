import pytest

from app.providers.base.provider import ShippingProvider
from app.providers.viettel_post import mapping
from app.providers.viettel_post.auth import LOGIN_PATH, OWNER_CONNECT_PATH
from app.providers.viettel_post.errors import (
    ViettelPostAuthError,
    ViettelPostBusinessError,
    ViettelPostInvalidResponseError,
)
from app.providers.viettel_post.provider import ViettelPostProvider
from tests.unit.vtp_fakes import (
    FAKE_LONG_TOKEN,
    FAKE_SHORT_TOKEN,
    Recorder,
    make_auth,
    make_client,
    ok,
    rejected,
    respond,
)

ROUTE = {
    "sender_province_id": 1,
    "sender_district_id": 12,
    "sender_ward_id": 49876,
    "receiver_province_id": 1,
    "receiver_district_id": 12,
    "receiver_ward_id": 49876,
}

# Response bodies copied from the official samples on partner2.viettelpost.vn/document.
SERVICES_SAMPLE = [
    {
        "MA_DV_CHINH": "PHS",
        "TEN_DICHVU": "Nội tỉnh tiết kiệm",
        "GIA_CUOC": 26400,
        "THOI_GIAN": "48 giờ",
        "EXCHANGE_WEIGHT": 0,
        "EXTRA_SERVICE": [
            {"SERVICE_CODE": "GBP", "SERVICE_NAME": "Báo phát", "DESCRIPTION": None},
        ],
    }
]
FEE_SAMPLE = ok(
    {
        "MONEY_TOTAL_OLD": 14700,
        "MONEY_TOTAL": 14700,
        "MONEY_TOTAL_FEE": 13363,
        "MONEY_FEE": 0,
        "MONEY_COLLECTION_FEE": 0,
        "MONEY_OTHER_FEE": 0,
        "MONEY_VAS": 0,
        "MONEY_VAT": 1337,
        "KPI_HT": 48,
    }
)
CREATE_SAMPLE = ok(
    {
        "ORDER_NUMBER": "15878180012",
        "MONEY_COLLECTION": 562000,
        "EXCHANGE_WEIGHT": 50,
        "MONEY_TOTAL": 16500,
        "MONEY_TOTAL_FEE": 15000,
        "MONEY_FEE": 0,
        "MONEY_COLLECTION_FEE": 0,
        "MONEY_OTHER_FEE": 0,
        "MONEY_VAS": 0,
        "MONEY_VAT": 1500,
        "KPI_HT": 48,
        "RECEIVER_PROVINCE": 34,
        "RECEIVER_DISTRICT": 390,
        "RECEIVER_WARD": 7393,
        "SORT_CODE": "HNI-CẦU GIẤY-NAT",
    }
)
CANCEL_SAMPLE = {"status": 200, "error": False, "message": "Hủy đơn hàng thành công", "data": None}


def provider_with(routes, *, static_token=FAKE_LONG_TOKEN):
    recorder = Recorder(routes)
    client = make_client(recorder)
    return ViettelPostProvider(client, make_auth(client, static_token=static_token)), recorder


def create_payload(**overrides):
    payload = {
        **ROUTE,
        "order_number": "VIP-0001",
        "sender_name": "Người gửi thử",
        "sender_phone": "0900000000",
        "sender_address": "Địa chỉ gửi thử",
        "receiver_name": "Người nhận thử",
        "receiver_phone": "0900000001",
        "receiver_address": "Địa chỉ nhận thử",
        "product_name": "Hàng thử",
        "product_type": "HH",
        "weight_grams": 100,
        "product_price": 990000,
        "cod_amount": 0,
        "order_payment": 1,
        "service_code": "VHT",
        "items": [{"name": "SP", "quantity": 1, "price": 990000, "weight_grams": 100}],
    }
    payload.update(overrides)
    return payload


def test_provider_implements_baseline_contract():
    provider, _ = provider_with({})
    assert isinstance(provider, ShippingProvider)
    assert provider.code == "VIETTEL_POST"


@pytest.mark.asyncio
async def test_get_services_mapping():
    provider, recorder = provider_with({mapping.GET_SERVICES_PATH: respond(SERVICES_SAMPLE)})

    services = await provider.api.get_services(
        {**ROUTE, "product_type": "HH", "weight_grams": 100, "price_table_type": 1}
    )

    assert services == [
        {
            "service_code": "PHS",
            "service_name": "Nội tỉnh tiết kiệm",
            "fee": 26400,
            "delivery_time": "48 giờ",
            "exchange_weight_grams": 0,
            "extra_services": [{"code": "GBP", "name": "Báo phát", "description": None}],
        }
    ]
    body = recorder.bodies(mapping.GET_SERVICES_PATH)[0]
    assert body["SENDER_WARD"] == 49876
    assert body["PRODUCT_WEIGHT"] == 100
    assert body["TYPE"] == 1
    assert recorder.requests[0].headers["Token"] == FAKE_LONG_TOKEN


@pytest.mark.asyncio
async def test_get_services_rejection_envelope_is_business_error():
    provider, _ = provider_with(
        {mapping.GET_SERVICES_PATH: respond(rejected("Price does not apply to this itinerary!"))}
    )
    with pytest.raises(ViettelPostBusinessError):
        await provider.api.get_services(
            {**ROUTE, "product_type": "HH", "weight_grams": 100, "price_table_type": 1}
        )


@pytest.mark.asyncio
async def test_get_services_undocumented_success_shape_is_invalid():
    provider, _ = provider_with({mapping.GET_SERVICES_PATH: respond(ok(SERVICES_SAMPLE))})
    with pytest.raises(ViettelPostInvalidResponseError):
        await provider.api.get_services(
            {**ROUTE, "product_type": "HH", "weight_grams": 100, "price_table_type": 1}
        )


@pytest.mark.asyncio
async def test_calculate_fee_mapping():
    provider, recorder = provider_with({mapping.CALCULATE_FEE_PATH: respond(FEE_SAMPLE)})

    quote = await provider.api.calculate_fee(
        {
            **ROUTE,
            "product_type": "HH",
            "weight_grams": 100,
            "product_price": 96000,
            "cod_amount": 0,
            "service_code": "VHT",
            "extra_service_codes": "",
            "price_table_type": 1,
        }
    )

    assert quote == {
        "total": 14700,
        "main_fee": 13363,
        "fuel_fee": 0,
        "cod_fee": 0,
        "other_fee": 0,
        "vat": 1337,
        "committed_delivery_time": 48,
    }
    body = recorder.bodies(mapping.CALCULATE_FEE_PATH)[0]
    assert body["ORDER_SERVICE"] == "VHT"
    assert body["ORDER_SERVICE_ADD"] == ""
    assert body["NATIONAL_TYPE"] == 1
    assert "TYPE" not in body


@pytest.mark.asyncio
async def test_calculate_fee_missing_total_is_invalid():
    provider, _ = provider_with({mapping.CALCULATE_FEE_PATH: respond(ok({"MONEY_VAT": 1}))})
    with pytest.raises(ViettelPostInvalidResponseError, match="MONEY_TOTAL"):
        await provider.api.calculate_fee(
            {
                **ROUTE,
                "product_type": "HH",
                "weight_grams": 100,
                "service_code": "VHT",
                "price_table_type": 1,
            }
        )


@pytest.mark.asyncio
async def test_create_shipment_mapping():
    provider, recorder = provider_with({mapping.CREATE_ORDER_PATH: respond(CREATE_SAMPLE)})

    result = await provider.api.create_order(
        create_payload(
            receiver_district_id=None,
            return_address={"required": True, "full_address": "Kho", "province_id": 1},
        )
    )

    assert result["tracking_number"] == "15878180012"
    assert result["total_fee"] == 16500
    assert result["cod_amount"] == 562000
    assert result["sort_code"] == "HNI-CẦU GIẤY-NAT"
    assert result["receiver_ward_id"] == 7393
    body = recorder.bodies(mapping.CREATE_ORDER_PATH)[0]
    assert body["ORDER_NUMBER"] == "VIP-0001"
    assert body["SENDER_FULLNAME"] == "Người gửi thử"
    assert body["RECEIVER_DISTRICT"] is None
    assert body["ORDER_PAYMENT"] == 1
    assert body["ORDER_SERVICE"] == "VHT"
    assert body["LIST_ITEM"] == [
        {
            "PRODUCT_NAME": "SP",
            "PRODUCT_QUANTITY": 1,
            "PRODUCT_PRICE": 990000,
            "PRODUCT_WEIGHT": 100,
        }
    ]
    assert body["RETURN_ADDRESS"] == {"REQUIRED": True, "FULLADDRESS": "Kho", "PROVINCE_ID": 1}


@pytest.mark.asyncio
async def test_create_shipment_rejection_is_business_error():
    provider, _ = provider_with(
        {mapping.CREATE_ORDER_PATH: respond(rejected("Incorrect data: ORDER_SERVICE"))}
    )
    with pytest.raises(ViettelPostBusinessError, match="ORDER_SERVICE"):
        await provider.api.create_order(create_payload())


@pytest.mark.asyncio
async def test_create_shipment_empty_order_number_is_invalid():
    provider, _ = provider_with({mapping.CREATE_ORDER_PATH: respond(ok({"ORDER_NUMBER": " "}))})
    with pytest.raises(ViettelPostInvalidResponseError):
        await provider.api.create_order(create_payload())


def test_create_rejects_unknown_field():
    with pytest.raises(ValueError, match="unsupported"):
        mapping.build_create_order_request(create_payload(receiver_email="x@example.test"))


def test_create_rejects_missing_required_field():
    payload = create_payload()
    del payload["receiver_phone"]
    with pytest.raises(ValueError, match="receiver_phone"):
        mapping.build_create_order_request(payload)


def test_create_rejects_null_required_field():
    with pytest.raises(ValueError, match="sender_ward_id"):
        mapping.build_create_order_request(create_payload(sender_ward_id=None))


def test_create_rejects_string_over_150_bytes():
    # 60 Vietnamese characters with diacritics exceed 150 UTF-8 bytes.
    with pytest.raises(ValueError, match="150 bytes"):
        mapping.build_create_order_request(create_payload(note="ồ" * 60))


@pytest.mark.asyncio
async def test_cancel_mapping():
    provider, recorder = provider_with({mapping.UPDATE_ORDER_STATUS_PATH: respond(CANCEL_SAMPLE)})

    result = await provider.api.cancel_order(" 301298000044 ")

    assert result == {
        "tracking_number": "301298000044",
        "cancelled": True,
        "message": "Hủy đơn hàng thành công",
    }
    assert recorder.bodies(mapping.UPDATE_ORDER_STATUS_PATH) == [
        {"TYPE": 4, "ORDER_NUMBER": "301298000044"}
    ]


@pytest.mark.asyncio
async def test_cancel_rejection_is_business_error():
    provider, _ = provider_with(
        {mapping.UPDATE_ORDER_STATUS_PATH: respond(rejected("Order does not exist"))}
    )
    with pytest.raises(ViettelPostBusinessError, match="Order does not exist"):
        await provider.api.cancel_order("301298000044")


@pytest.mark.asyncio
async def test_cancel_requires_tracking_number():
    provider, recorder = provider_with({})
    with pytest.raises(ValueError):
        await provider.api.cancel_order("  ")
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_get_shipment_not_implemented():
    provider, recorder = provider_with({})
    with pytest.raises(NotImplementedError):
        await provider.get_shipment("301298000044")
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_expired_token_is_refreshed_once():
    calls = {"n": 0}

    def fee(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return respond(rejected("Token invalid or expired"))(request)
        return respond(FEE_SAMPLE)(request)

    login_tokens = iter([FAKE_SHORT_TOKEN, FAKE_SHORT_TOKEN])
    owner_tokens = iter(["eyJfake.eyJfirst.sig", FAKE_LONG_TOKEN])
    provider, recorder = provider_with(
        {
            LOGIN_PATH: lambda r: respond(ok({"token": next(login_tokens)}))(r),
            OWNER_CONNECT_PATH: lambda r: respond(ok({"token": next(owner_tokens)}))(r),
            mapping.CALCULATE_FEE_PATH: fee,
        },
        static_token="",
    )

    quote = await provider.api.calculate_fee(
        {
            **ROUTE,
            "product_type": "HH",
            "weight_grams": 1,
            "service_code": "VHT",
            "price_table_type": 1,
        }
    )

    assert quote["total"] == 14700
    fee_requests = [r for r in recorder.requests if r.url.path == mapping.CALCULATE_FEE_PATH]
    assert [r.headers["Token"] for r in fee_requests] == ["eyJfake.eyJfirst.sig", FAKE_LONG_TOKEN]


@pytest.mark.asyncio
async def test_static_token_rejection_is_not_retried():
    provider, recorder = provider_with(
        {mapping.UPDATE_ORDER_STATUS_PATH: respond(rejected("Token invalid"))}
    )
    with pytest.raises(ViettelPostAuthError) as info:
        await provider.api.cancel_order("301298000044")
    assert len(recorder.requests) == 1
    assert FAKE_LONG_TOKEN not in str(info.value)
