"""Viettel Post adapter implementing the typed ``ShippingProvider`` contract.

Typed core DTOs are translated here into the snake_case payloads of ``ViettelPostApi``
(which ``mapping.py`` turns into Viettel Post field names). Carrier-only inputs come from
``provider_options`` validated as ``ViettelPostOptions``. Tokens never leave the adapter.
"""

import hmac
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import ValidationError

from app.domain.models.common import Address, Money, ShippingProviderCode
from app.domain.models.shipment import ShipmentPackage, ShipmentStatus
from app.providers.base.dto import (
    AuthResult,
    CancelShipmentResult,
    CreateShipmentRequest,
    CreateShipmentResult,
    FeeQuote,
    FeeRequest,
    ServiceOption,
    ServiceQuery,
    ShipmentSnapshot,
    WebhookRequest,
    WebhookResult,
)
from app.providers.base.errors import ProviderRequestError
from app.providers.base.provider import ShippingProvider
from app.providers.viettel_post.api import ViettelPostApi
from app.providers.viettel_post.auth import ViettelPostAuth
from app.providers.viettel_post.client import ViettelPostClient
from app.providers.viettel_post.events import to_shipment_event
from app.providers.viettel_post.options import ViettelPostOptions, VtpLocationIds
from app.providers.viettel_post.status_mapper import map_status
from app.webhooks.viettel_post_payload import (
    RejectionKind,
    WebhookRejected,
    envelope_from_payload,
    parse_event,
)

VND = "VND"

# ORDER_PAYMENT codes that do not collect the goods value (D-BIZ-001, docs/DECISIONS.md).
NON_COLLECTING_ORDER_PAYMENTS = frozenset({1, 4})


class ViettelPostRequestError(ProviderRequestError):
    """A core request cannot be expressed as a Viettel Post request (caller error)."""


def _options(raw: dict[str, Any]) -> ViettelPostOptions:
    try:
        return ViettelPostOptions.model_validate(raw)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
        raise ViettelPostRequestError(f"invalid Viettel Post provider_options: {fields}") from exc


def to_vnd(money: Money | None, what: str) -> int | None:
    """Viettel Post amounts are integer VND."""
    if money is None:
        return None
    if money.currency != VND:
        raise ViettelPostRequestError(
            f"{what}: Viettel Post only accepts VND, got {money.currency}"
        )
    if money.amount != money.amount.to_integral_value():
        raise ViettelPostRequestError(f"{what}: Viettel Post amounts are whole VND")
    return int(money.amount)


def from_vnd(value: Any) -> Money | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return Money(amount=Decimal(value), currency=VND)


def _route(options: ViettelPostOptions) -> dict[str, Any]:
    def ids(prefix: str, loc: VtpLocationIds) -> dict[str, Any]:
        return {
            f"{prefix}_province_id": loc.province_id,
            f"{prefix}_district_id": loc.district_id,
            f"{prefix}_ward_id": loc.ward_id,
        }

    return {**ids("sender", options.sender_location), **ids("receiver", options.receiver_location)}


def _parcel(
    packages: list[ShipmentPackage], cod: Money | None, options: ViettelPostOptions
) -> dict[str, Any]:
    """Viettel Post takes one parcel: total weight, one set of dimensions, one value."""
    parcel: dict[str, Any] = {
        "product_type": options.product_type,
        "weight_grams": sum(p.weight_grams for p in packages),
        # No COD is sent as 0 (domain None == no collection).
        "cod_amount": to_vnd(cod, "cod_amount") or 0,
    }
    if len(packages) == 1:
        # Dimensions of several boxes cannot be combined into one without guessing.
        only = packages[0]
        for key in ("length_cm", "width_cm", "height_cm"):
            value = getattr(only, key)
            if value is not None:
                parcel[key] = value
    price = options.product_price_vnd
    if price is None and all(p.declared_value is not None for p in packages):
        price = sum(to_vnd(p.declared_value, "declared_value") or 0 for p in packages)
    if price is not None:
        parcel["product_price"] = price
    return parcel


def _full_address(address: Address) -> str:
    parts = [address.address_line, address.ward, address.district, address.province]
    return ", ".join(p for p in parts if p)


class ViettelPostProvider(ShippingProvider):
    """Viettel Post adapter. Endpoints follow https://partner2.viettelpost.vn/document."""

    code: ClassVar[ShippingProviderCode] = ShippingProviderCode.VIETTEL_POST

    def __init__(
        self,
        client: ViettelPostClient | None = None,
        auth: ViettelPostAuth | None = None,
        *,
        webhook_secret: str | None = None,
        webhook_timezone: tzinfo | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.api = ViettelPostApi(client, auth)
        self._webhook_secret = webhook_secret or None
        self._webhook_tz = webhook_timezone
        self._clock = clock

    @property
    def client(self) -> ViettelPostClient:
        return self.api.client

    @property
    def auth(self) -> ViettelPostAuth:
        return self.api.auth

    async def close(self) -> None:
        await self.api.client.close()

    async def authenticate(self) -> AuthResult:
        await self.api.auth.authenticate()
        # The token stays in the adapter. Viettel Post documents no expiry for Login
        # tokens and "1 year" for ownerconnect without a timestamp, so none is reported.
        return AuthResult(provider=self.code, authenticated=True, expires_at=None)

    async def get_services(self, query: ServiceQuery) -> list[ServiceOption]:
        options = _options(query.provider_options)
        payload = {
            **_route(options),
            **_parcel(query.packages, query.cod_amount, options),
            "price_table_type": options.price_table_type,
        }
        services = await self.api.get_services(payload)
        return [
            ServiceOption(
                provider=self.code,
                service_code=s["service_code"],
                name=s.get("service_name") or s["service_code"],
                estimated_fee=from_vnd(s.get("fee")),
            )
            for s in services
        ]

    async def calculate_fee(self, request: FeeRequest) -> FeeQuote:
        if not request.service_code:
            raise ViettelPostRequestError("calculate_fee: Viettel Post requires service_code")
        options = _options(request.provider_options)
        payload = {
            **_route(options),
            **_parcel(request.packages, request.cod_amount, options),
            "price_table_type": options.price_table_type,
            "service_code": request.service_code,
        }
        if options.extra_service_codes:
            payload["extra_service_codes"] = options.extra_service_codes
        fee = await self.api.calculate_fee(payload)
        total = from_vnd(fee["total"])
        if total is None:
            raise ViettelPostRequestError("calculate_fee: Viettel Post returned no usable total")
        return FeeQuote(provider=self.code, total=total, service_code=request.service_code)

    async def create_shipment(self, request: CreateShipmentRequest) -> CreateShipmentResult:
        if not request.service_code:
            raise ViettelPostRequestError("create_shipment: Viettel Post requires service_code")
        options = _options(request.provider_options)
        if options.order_payment is None:
            raise ViettelPostRequestError(
                "create_shipment: provider_options.order_payment (1-4) is required"
            )
        # D-BIZ-001 (owner, 2026-10-02): COD -> 3, non-COD -> 1; a COD amount with a code that
        # does not collect the goods value (1, 4) is refused before any call, so a COD order can
        # never be sent with "no collection".
        cod = request.cod_amount.amount if request.cod_amount is not None else 0
        if cod > 0 and options.order_payment in NON_COLLECTING_ORDER_PAYMENTS:
            raise ViettelPostRequestError(
                "create_shipment: cod_amount > 0 requires order_payment 2 or 3 (D-BIZ-001)"
            )
        payload: dict[str, Any] = {
            **_route(options),
            **_parcel(request.packages, request.cod_amount, options),
            "order_number": request.order_id,
            "sender_name": request.sender.name,
            "sender_phone": request.sender.phone,
            "sender_address": _full_address(request.sender),
            "receiver_name": request.receiver.name,
            "receiver_phone": request.receiver.phone,
            "receiver_address": _full_address(request.receiver),
            "order_payment": options.order_payment,
            "service_code": request.service_code,
        }
        optional = {
            "extra_service_codes": options.extra_service_codes,
            "product_name": options.product_name,
            "product_quantity": options.product_quantity,
            "note": request.note,
        }
        payload.update({k: v for k, v in optional.items() if v is not None})
        if options.items:
            payload["items"] = [
                {
                    "name": i.name,
                    "quantity": i.quantity,
                    "price": i.price_vnd,
                    "weight_grams": i.weight_grams,
                }
                for i in options.items
            ]
        try:
            created = await self.api.create_order(payload)
        except ValueError as exc:
            if isinstance(exc, ViettelPostRequestError):
                raise
            raise ViettelPostRequestError(str(exc)) from exc
        return CreateShipmentResult(
            provider=self.code,
            order_id=request.order_id,
            tracking_number=created["tracking_number"],
            # A successful createOrder means the order exists at Viettel Post.
            status=ShipmentStatus.CREATED,
            fee=from_vnd(created.get("total_fee")),
        )

    async def get_shipment(self, tracking_number: str) -> ShipmentSnapshot:
        # The Partner docs (partner2.viettelpost.vn/document, checked 2026-09-29) list no
        # order lookup API; status arrives by webhook. Not implemented until VTP confirms one.
        raise NotImplementedError(
            "Viettel Post chưa công bố API tra cứu vận đơn trong tài liệu Partner chính thức."
        )

    async def cancel_shipment(
        self, tracking_number: str, *, note: str | None = None
    ) -> CancelShipmentResult:
        """``note`` is sent as UpdateOrder ``NOTE`` (optional per the official page)."""
        try:
            cancelled = await self.api.cancel_order(tracking_number, note)
        except ValueError as exc:
            raise ViettelPostRequestError(str(exc)) from exc
        return CancelShipmentResult(
            provider=self.code,
            tracking_number=cancelled["tracking_number"],
            cancelled=True,
            status=ShipmentStatus.CANCELLED,
        )

    async def handle_webhook(self, request: WebhookRequest) -> WebhookResult:
        """Stateless parse of one Viettel Post webhook: TOKEN check, validation, mapping.

        Idempotency, persistence and shipment updates are done by the durable pipeline
        (``app.webhooks.processor``), which reuses the same parsing and event building.
        Raises ``WebhookRejected`` for an unauthenticated or malformed request.
        """
        if self._webhook_secret is None:
            raise WebhookRejected(RejectionKind.NOT_CONFIGURED, "webhook secret not configured")
        envelope = envelope_from_payload(request.payload)
        token = envelope.token
        if (
            not isinstance(token, str)
            or not token
            or not hmac.compare_digest(token.encode("utf-8"), self._webhook_secret.encode("utf-8"))
        ):
            raise WebhookRejected(RejectionKind.UNAUTHORIZED, "TOKEN invalid")
        parsed = parse_event(envelope)
        event = to_shipment_event(
            parsed,
            map_status(parsed.provider_status),
            received_at=self._clock(),
            tz=self._webhook_tz,
        )
        return WebhookResult(provider=self.code, accepted=True, events=[event])
