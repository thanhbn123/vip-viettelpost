import asyncio
import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.models import (
    Address,
    Money,
    ShipmentEvent,
    ShipmentPackage,
    ShipmentStatus,
    ShippingProviderCode,
)
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
from app.providers.base.provider import ShippingProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_DIRS = [REPO_ROOT / "app" / "domain", REPO_ROOT / "app" / "providers" / "base"]

CONTRACT_METHODS = {
    "authenticate",
    "get_services",
    "calculate_fee",
    "create_shipment",
    "get_shipment",
    "cancel_shipment",
    "handle_webhook",
}

ADDRESS = Address(name="A", phone="0900000000", address_line="1 Street", province="Ha Noi")
PACKAGE = ShipmentPackage(weight_grams=500)


class FakeProvider(ShippingProvider):
    """In-memory provider used to exercise the contract without any network."""

    code = ShippingProviderCode.VIPORDER_FLEET

    async def authenticate(self) -> AuthResult:
        return AuthResult(provider=self.code, authenticated=True)

    async def get_services(self, query: ServiceQuery) -> list[ServiceOption]:
        return [ServiceOption(provider=self.code, service_code="STD", name="Standard")]

    async def calculate_fee(self, request: FeeRequest) -> FeeQuote:
        return FeeQuote(provider=self.code, total=Money(amount=10 * len(request.packages)))

    async def create_shipment(self, request: CreateShipmentRequest) -> CreateShipmentResult:
        return CreateShipmentResult(
            provider=self.code,
            order_id=request.order_id,
            tracking_number="FLEET-1",
            status=ShipmentStatus.CREATED,
        )

    async def get_shipment(self, tracking_number: str) -> ShipmentSnapshot:
        return ShipmentSnapshot(
            provider=self.code, tracking_number=tracking_number, status=ShipmentStatus.IN_TRANSIT
        )

    async def cancel_shipment(self, tracking_number: str) -> CancelShipmentResult:
        return CancelShipmentResult(
            provider=self.code,
            tracking_number=tracking_number,
            cancelled=True,
            status=ShipmentStatus.CANCELLED,
        )

    async def handle_webhook(self, request: WebhookRequest) -> WebhookResult:
        event = ShipmentEvent(
            provider=self.code,
            tracking_number=request.payload["tracking_number"],
            status=ShipmentStatus.DELIVERED,
            occurred_at=datetime(2026, 9, 29, 12, 0, tzinfo=timezone(timedelta(hours=7))),
        )
        return WebhookResult(provider=self.code, accepted=True, events=[event])


# --- provider code ----------------------------------------------------------


def test_provider_codes():
    assert {c.value for c in ShippingProviderCode} == {
        "VIETTEL_POST",
        "SUPERSHIP",
        "GHN",
        "GHTK",
        "VIPORDER_FLEET",
    }


def test_unknown_provider_code_rejected():
    with pytest.raises(ValueError):
        ShippingProviderCode("UNKNOWN")


def test_subclass_with_undeclared_code_rejected():
    with pytest.raises(ValueError):

        class BadProvider(FakeProvider):
            code = "NOT_A_PROVIDER"


# --- contract ---------------------------------------------------------------


def test_contract_declares_exactly_the_required_methods():
    assert ShippingProvider.__abstractmethods__ == CONTRACT_METHODS
    for name in CONTRACT_METHODS:
        assert inspect.iscoroutinefunction(getattr(ShippingProvider, name)), name


def test_contract_cannot_be_instantiated():
    with pytest.raises(TypeError):
        ShippingProvider()


def test_incomplete_provider_cannot_be_instantiated():
    class Partial(ShippingProvider):
        code = ShippingProviderCode.GHN

        async def authenticate(self) -> AuthResult:
            return AuthResult(provider=self.code, authenticated=True)

    with pytest.raises(TypeError):
        Partial()


def test_fake_provider_round_trip():
    provider = FakeProvider()
    request = CreateShipmentRequest(
        order_id="ORD-1", sender=ADDRESS, receiver=ADDRESS, packages=[PACKAGE]
    )

    async def run():
        auth = await provider.authenticate()
        services = await provider.get_services(
            ServiceQuery(sender=ADDRESS, receiver=ADDRESS, packages=[PACKAGE])
        )
        fee = await provider.calculate_fee(
            FeeRequest(sender=ADDRESS, receiver=ADDRESS, packages=[PACKAGE, PACKAGE])
        )
        created = await provider.create_shipment(request)
        snapshot = await provider.get_shipment(created.tracking_number)
        cancelled = await provider.cancel_shipment(created.tracking_number)
        hook = await provider.handle_webhook(WebhookRequest(payload={"tracking_number": "F-2"}))
        return auth, services, fee, created, snapshot, cancelled, hook

    auth, services, fee, created, snapshot, cancelled, hook = asyncio.run(run())
    assert auth.authenticated is True
    assert services[0].service_code == "STD"
    assert fee.total == Money(amount=20)
    assert created.status is ShipmentStatus.CREATED
    assert snapshot.status is ShipmentStatus.IN_TRANSIT
    assert cancelled.status is ShipmentStatus.CANCELLED
    assert hook.events[0].status is ShipmentStatus.DELIVERED


def test_auth_result_carries_no_credential_field():
    fields = set(AuthResult.model_fields)
    assert fields == {"provider", "authenticated", "expires_at"}
    with pytest.raises(ValidationError):
        AuthResult(provider="GHN", authenticated=True, token="x")


# --- request validation -----------------------------------------------------


def test_create_request_with_zero_packages_rejected():
    with pytest.raises(ValidationError):
        CreateShipmentRequest(order_id="ORD-1", sender=ADDRESS, receiver=ADDRESS, packages=[])


def test_create_request_empty_order_id_rejected():
    with pytest.raises(ValidationError):
        CreateShipmentRequest(order_id=" ", sender=ADDRESS, receiver=ADDRESS, packages=[PACKAGE])


def test_create_request_package_count():
    request = CreateShipmentRequest(
        order_id="ORD-1", sender=ADDRESS, receiver=ADDRESS, packages=[PACKAGE, PACKAGE]
    )
    assert request.package_count == 2


@pytest.mark.parametrize("model", [ServiceQuery, FeeRequest])
def test_quote_requests_need_a_package(model):
    with pytest.raises(ValidationError):
        model(sender=ADDRESS, receiver=ADDRESS, packages=[])


def test_result_rejects_unknown_status():
    with pytest.raises(ValidationError):
        CreateShipmentResult(
            provider="GHN", order_id="ORD-1", tracking_number="T", status="PROVIDER_CODE_42"
        )


def test_dto_json_round_trip():
    request = CreateShipmentRequest(
        order_id="ORD-1",
        sender=ADDRESS,
        receiver=ADDRESS,
        packages=[PACKAGE],
        cod_amount=Money(amount="150000"),
        idempotency_key="ORD-1:create",
    )
    assert CreateShipmentRequest.model_validate_json(request.model_dump_json()) == request


# --- provider independence --------------------------------------------------


def _core_sources():
    files = [p for d in CORE_DIRS for p in d.rglob("*.py")]
    assert files
    return {p: p.read_text(encoding="utf-8") for p in files}


def test_core_does_not_import_provider_adapters_or_infrastructure():
    forbidden = re.compile(
        r"^\s*(from|import)\s+(app\.providers\.(?!base\b)|app\.(db|repositories|api|webhooks|"
        r"services|core)\b|httpx|sqlalchemy|alembic|fastapi)",
        re.M,
    )
    offenders = {str(p): forbidden.findall(src) for p, src in _core_sources().items()}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_core_has_no_urls_or_carrier_specific_config():
    # The provider *code* VIETTEL_POST is allowed; URLs, carrier domains and
    # carrier config/credential names are not.
    forbidden = re.compile(r"https?://|viettelpost|\bvtp_", re.I)
    offenders = [str(p) for p, src in _core_sources().items() if forbidden.search(src)]
    assert offenders == []


def test_existing_viettel_post_adapter_still_satisfies_contract():
    # Read-only check: the adapter is owned by another worker and not modified here.
    from app.providers.viettel_post.provider import ViettelPostProvider

    assert issubclass(ViettelPostProvider, ShippingProvider)
    assert not inspect.isabstract(ViettelPostProvider)
    assert ShippingProviderCode(ViettelPostProvider.code) is ShippingProviderCode.VIETTEL_POST
