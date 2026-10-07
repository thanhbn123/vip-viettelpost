"""Translation between adapter payloads and Viettel Post request/response bodies.

Every Viettel Post field name lives in this module. Callers pass snake_case payloads; the
adapter returns snake_case dictionaries, so raw Viettel Post keys do not reach the core.

Field lists follow the official pages (checked 2026-09-29):
- services:  https://partner2.viettelpost.vn/document/get-list-service-by-address-id
- fee:       https://partner2.viettelpost.vn/document/charges-id-address
- create:    https://partner2.viettelpost.vn/document/create-order-id-address
- cancel:    https://partner2.viettelpost.vn/document/update-bill-of-lading-status

A payload key that has no mapping raises ``ValueError`` instead of being dropped silently.
"""

from collections.abc import Mapping
from typing import Any

from app.providers.viettel_post.errors import ViettelPostInvalidResponseError

GET_SERVICES_PATH = "/v2/order/getPriceAll"
CALCULATE_FEE_PATH = "/v2/order/getPrice"
CREATE_ORDER_PATH = "/v2/order/createOrder"
UPDATE_ORDER_STATUS_PATH = "/v2/order/UpdateOrder"

# UpdateOrder TYPE values from the official page.
UPDATE_TYPE_CANCEL = 4

# "Đối với các trường dữ liệu kiểu String, maxlength mặc định là 150 bytes" (create order page).
MAX_STRING_BYTES = 150

_ROUTE_FIELDS = {
    "sender_province_id": "SENDER_PROVINCE",
    "sender_district_id": "SENDER_DISTRICT",
    "sender_ward_id": "SENDER_WARD",
    "receiver_province_id": "RECEIVER_PROVINCE",
    "receiver_district_id": "RECEIVER_DISTRICT",
    "receiver_ward_id": "RECEIVER_WARD",
}
_PARCEL_FIELDS = {
    "product_type": "PRODUCT_TYPE",
    "weight_grams": "PRODUCT_WEIGHT",
    "product_price": "PRODUCT_PRICE",
    "cod_amount": "MONEY_COLLECTION",
    "length_cm": "PRODUCT_LENGTH",
    "width_cm": "PRODUCT_WIDTH",
    "height_cm": "PRODUCT_HEIGHT",
}
_ROUTE_REQUIRED = frozenset(_ROUTE_FIELDS)
# The official create-order sample sends ``SENDER_DISTRICT: null`` for new 2-level addresses,
# so district keys must be present but may be ``None``.
_NULLABLE = frozenset({"sender_district_id", "receiver_district_id"})

SERVICES_FIELDS = {**_ROUTE_FIELDS, **_PARCEL_FIELDS, "price_table_type": "TYPE"}
SERVICES_REQUIRED = _ROUTE_REQUIRED | {"product_type", "weight_grams", "price_table_type"}

FEE_FIELDS = {
    **_ROUTE_FIELDS,
    **_PARCEL_FIELDS,
    "price_table_type": "NATIONAL_TYPE",
    "service_code": "ORDER_SERVICE",
    "extra_service_codes": "ORDER_SERVICE_ADD",
}
FEE_REQUIRED = _ROUTE_REQUIRED | {
    "product_type",
    "weight_grams",
    "price_table_type",
    "service_code",
}

CREATE_FIELDS = {
    **_ROUTE_FIELDS,
    **_PARCEL_FIELDS,
    "order_number": "ORDER_NUMBER",
    "sender_name": "SENDER_FULLNAME",
    "sender_phone": "SENDER_PHONE",
    "sender_address": "SENDER_ADDRESS",
    "receiver_name": "RECEIVER_FULLNAME",
    "receiver_phone": "RECEIVER_PHONE",
    "receiver_address": "RECEIVER_ADDRESS",
    "pickup_date": "PICKUP_DATE",
    "pickup_code": "PICKUP_CODE",
    "delivery_code": "DELIVERY_CODE",
    "product_name": "PRODUCT_NAME",
    "product_quantity": "PRODUCT_QUANTITY",
    "order_payment": "ORDER_PAYMENT",
    "service_code": "ORDER_SERVICE",
    "extra_service_codes": "ORDER_SERVICE_ADD",
    "note": "ORDER_NOTE",
    "items": "LIST_ITEM",
    "return_address": "RETURN_ADDRESS",
    "group_address_id": "GROUPADDRESS_ID",
    "check_unique": "CHECK_UNIQUE",
    "extra_money": "EXTRA_MONEY",
    "enable_sort_code": "ENABLE_SORT_CODE",
}
CREATE_REQUIRED = _ROUTE_REQUIRED | {
    "sender_name",
    "sender_phone",
    "sender_address",
    "receiver_name",
    "receiver_phone",
    "receiver_address",
    "order_payment",
    "service_code",
}
ITEM_FIELDS = {
    "name": "PRODUCT_NAME",
    "quantity": "PRODUCT_QUANTITY",
    "price": "PRODUCT_PRICE",
    "weight_grams": "PRODUCT_WEIGHT",
}
RETURN_ADDRESS_FIELDS = {
    "required": "REQUIRED",
    "full_address": "FULLADDRESS",
    "province_id": "PROVINCE_ID",
    "district_id": "DISTRICT_ID",
    "ward_id": "WARDS_ID",
}


def _translate(
    payload: Mapping[str, Any],
    fields: Mapping[str, str],
    required: frozenset[str] = frozenset(),
    *,
    what: str,
) -> dict[str, Any]:
    unknown = sorted(set(payload) - set(fields))
    if unknown:
        raise ValueError(f"{what}: unsupported field(s) {unknown}")
    missing = sorted(
        key
        for key in required
        if key not in payload or (payload[key] is None and key not in _NULLABLE)
    )
    if missing:
        raise ValueError(f"{what}: missing required field(s) {missing}")
    return {fields[key]: value for key, value in payload.items()}


def _check_string_lengths(body: Mapping[str, Any], what: str) -> None:
    for key, value in body.items():
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ValueError(f"{what}: {key} exceeds {MAX_STRING_BYTES} bytes")


def build_get_services_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _translate(payload, SERVICES_FIELDS, SERVICES_REQUIRED, what="get_services")


def build_calculate_fee_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _translate(payload, FEE_FIELDS, FEE_REQUIRED, what="calculate_fee")


def build_create_order_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    body = _translate(payload, CREATE_FIELDS, CREATE_REQUIRED, what="create_shipment")
    if "LIST_ITEM" in body:
        body["LIST_ITEM"] = [
            _translate(item, ITEM_FIELDS, what="create_shipment.items")
            for item in body["LIST_ITEM"]
        ]
        for item in body["LIST_ITEM"]:
            _check_string_lengths(item, "create_shipment.items")
    if body.get("RETURN_ADDRESS") is not None:
        body["RETURN_ADDRESS"] = _translate(
            body["RETURN_ADDRESS"], RETURN_ADDRESS_FIELDS, what="create_shipment.return_address"
        )
        _check_string_lengths(body["RETURN_ADDRESS"], "create_shipment.return_address")
    _check_string_lengths(body, "create_shipment")
    return body


def build_cancel_request(tracking_number: str, note: str | None = None) -> dict[str, Any]:
    if not tracking_number or not tracking_number.strip():
        raise ValueError("cancel_shipment: tracking_number is required")
    body: dict[str, Any] = {"TYPE": UPDATE_TYPE_CANCEL, "ORDER_NUMBER": tracking_number.strip()}
    if note:
        # The page limits NOTE to 150 characters.
        if len(note) > MAX_STRING_BYTES:
            raise ValueError("cancel_shipment: note exceeds 150 characters")
        body["NOTE"] = note
    return body


def _data_object(envelope: Mapping[str, Any], path: str) -> dict[str, Any]:
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise ViettelPostInvalidResponseError(f"Viettel Post {path} response has no data object")
    return data


def _require(data: Mapping[str, Any], key: str, path: str, kind: type | tuple[type, ...]) -> Any:
    value = data.get(key)
    if not isinstance(value, kind) or isinstance(value, bool):
        raise ViettelPostInvalidResponseError(f"Viettel Post {path} response has no valid {key}")
    return value


def parse_services_response(body: Any) -> list[dict[str, Any]]:
    """The official sample for getPriceAll is a bare JSON array, not the usual envelope."""
    if not isinstance(body, list):
        raise ViettelPostInvalidResponseError(
            f"Viettel Post {GET_SERVICES_PATH} response is not the documented array"
        )
    services = []
    for entry in body:
        if not isinstance(entry, dict):
            raise ViettelPostInvalidResponseError(
                f"Viettel Post {GET_SERVICES_PATH} response contains a non-object entry"
            )
        services.append(
            {
                "service_code": _require(entry, "MA_DV_CHINH", GET_SERVICES_PATH, str),
                "service_name": entry.get("TEN_DICHVU"),
                "fee": entry.get("GIA_CUOC"),
                "delivery_time": entry.get("THOI_GIAN"),
                "exchange_weight_grams": entry.get("EXCHANGE_WEIGHT"),
                "extra_services": [
                    {
                        "code": extra.get("SERVICE_CODE"),
                        "name": extra.get("SERVICE_NAME"),
                        "description": extra.get("DESCRIPTION"),
                    }
                    for extra in entry.get("EXTRA_SERVICE") or []
                    if isinstance(extra, dict)
                ],
            }
        )
    return services


def parse_fee_response(envelope: Mapping[str, Any]) -> dict[str, Any]:
    data = _data_object(envelope, CALCULATE_FEE_PATH)
    return {
        "total": _require(data, "MONEY_TOTAL", CALCULATE_FEE_PATH, int),
        "main_fee": data.get("MONEY_TOTAL_FEE"),
        "fuel_fee": data.get("MONEY_FEE"),
        "cod_fee": data.get("MONEY_COLLECTION_FEE"),
        "other_fee": data.get("MONEY_OTHER_FEE"),
        "vat": data.get("MONEY_VAT"),
        # KPI_HT: "Tổng thời gian giao hàng cam kết"; the page does not state the unit.
        "committed_delivery_time": data.get("KPI_HT"),
    }


def parse_create_order_response(envelope: Mapping[str, Any]) -> dict[str, Any]:
    data = _data_object(envelope, CREATE_ORDER_PATH)
    tracking_number = _require(data, "ORDER_NUMBER", CREATE_ORDER_PATH, str).strip()
    if not tracking_number:
        raise ViettelPostInvalidResponseError(
            f"Viettel Post {CREATE_ORDER_PATH} response has an empty ORDER_NUMBER"
        )
    return {
        "tracking_number": tracking_number,
        "cod_amount": data.get("MONEY_COLLECTION"),
        "total_fee": data.get("MONEY_TOTAL"),
        "main_fee": data.get("MONEY_TOTAL_FEE"),
        "fuel_fee": data.get("MONEY_FEE"),
        "cod_fee": data.get("MONEY_COLLECTION_FEE"),
        "vat": data.get("MONEY_VAT"),
        "committed_delivery_time": data.get("KPI_HT"),
        "exchange_weight_grams": data.get("EXCHANGE_WEIGHT"),
        "receiver_province_id": data.get("RECEIVER_PROVINCE"),
        "receiver_district_id": data.get("RECEIVER_DISTRICT"),
        "receiver_ward_id": data.get("RECEIVER_WARD"),
        "sort_code": data.get("SORT_CODE"),
    }


def parse_cancel_response(envelope: Mapping[str, Any], tracking_number: str) -> dict[str, Any]:
    # The official sample returns ``data: null``; success is signalled by ``error: false``.
    return {
        "tracking_number": tracking_number.strip(),
        "cancelled": True,
        "message": envelope.get("message"),
    }
