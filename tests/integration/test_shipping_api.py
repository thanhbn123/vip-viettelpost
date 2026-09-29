"""Provider-neutral shipping API over a real migrated database and a fake provider."""

import asyncio
import threading
from decimal import Decimal
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.dependencies import get_application
from app.db.models import Shipment as ShipmentRecord
from app.db.models import ShippingAuditLog
from app.db.session import make_engine, make_session_factory
from app.domain.models import Money, ShipmentStatus, ShippingProviderCode
from app.main import app
from app.providers.base.dto import (
    AuthResult,
    CancelShipmentResult,
    CreateShipmentResult,
    FeeQuote,
    ServiceOption,
    WebhookResult,
)
from app.providers.base.errors import (
    ProviderAuthError,
    ProviderRejectedError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.providers.base.provider import ShippingProvider
from app.services.shipping_app import ShippingApplication

SECRET_TOKEN = "eyJfake.never.returned"
BASE = "/api/v1/shipping"


class FakeProvider(ShippingProvider):
    code: ClassVar[ShippingProviderCode] = ShippingProviderCode.VIETTEL_POST

    def __init__(self) -> None:
        self.fail_with: dict[str, Exception] = {}
        self.calls: list[str] = []
        self.counter = 0
        self.delay = 0.0

    def _maybe_fail(self, name):
        self.calls.append(name)
        if name in self.fail_with:
            raise self.fail_with[name]

    async def authenticate(self):
        return AuthResult(provider=self.code, authenticated=True)

    async def get_services(self, query):
        return [ServiceOption(provider=self.code, service_code="S", name="S")]

    async def calculate_fee(self, request):
        self._maybe_fail("calculate_fee")
        return FeeQuote(provider=self.code, total=Money(amount=14700), service_code="VCN")

    async def create_shipment(self, request):
        if self.delay:
            await asyncio.sleep(self.delay)
        self._maybe_fail("create_shipment")
        self.counter += 1
        return CreateShipmentResult(
            provider=self.code,
            order_id=request.order_id,
            tracking_number=f"TRK{self.counter:04d}",
            status=ShipmentStatus.CREATED,
            fee=Money(amount=16500),
        )

    async def get_shipment(self, tracking_number):
        raise NotImplementedError

    async def cancel_shipment(self, tracking_number):
        self._maybe_fail("cancel_shipment")
        return CancelShipmentResult(
            provider=self.code,
            tracking_number=tracking_number,
            cancelled=True,
            status=ShipmentStatus.CANCELLED,
        )

    async def handle_webhook(self, request):
        return WebhookResult(provider=self.code, accepted=True)


ADDRESS = {"name": "A", "phone": "0900000000", "address_line": "1 Đường A", "province": "Hà Nội"}


def create_body(order_id="ORD-1", **overrides):
    body = {
        "provider": "VIETTEL_POST",
        "order_id": order_id,
        "sender": ADDRESS,
        "receiver": ADDRESS,
        "packages": [{"weight_grams": 500}],
        "service_code": "VCN",
        "cod_amount": {"amount": "150000"},
    }
    body.update(overrides)
    return body


@pytest.fixture
def env(migrated_url):
    engine = make_engine(migrated_url)
    sessions = make_session_factory(engine)
    provider = FakeProvider()
    application = ShippingApplication({ShippingProviderCode.VIETTEL_POST: provider}, sessions)
    app.dependency_overrides[get_application] = lambda: application
    with TestClient(app) as client:
        yield client, provider, sessions
    app.dependency_overrides.clear()
    engine.dispose()


def audit_actions(sessions, shipment_id):
    with sessions() as s:
        return [
            row.action
            for row in s.scalars(
                select(ShippingAuditLog)
                .where(ShippingAuditLog.entity_id == str(shipment_id))
                .order_by(ShippingAuditLog.id)
            )
        ]


def status_of(sessions, shipment_id):
    with sessions() as s:
        return s.get(ShipmentRecord, shipment_id).status


def test_health(env):
    client, _, _ = env
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_providers_list(env):
    client, _, _ = env
    providers = {p["code"]: p for p in client.get(f"{BASE}/providers").json()}
    assert providers["VIETTEL_POST"] == {
        "code": "VIETTEL_POST",
        "adapter_available": True,
        "enabled": True,
    }
    assert providers["GHN"]["adapter_available"] is False and providers["GHN"]["enabled"] is False


def test_quote(env):
    client, _, _ = env
    body = {k: v for k, v in create_body().items() if k not in ("order_id",)}
    response = client.post(f"{BASE}/quote", json=body)
    assert response.status_code == 200
    assert Decimal(response.json()["total"]["amount"]) == Decimal(14700)


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (ProviderTimeoutError("t"), 504, "provider_timeout"),
        (ProviderUnavailableError("u"), 503, "provider_unavailable"),
        (ProviderRejectedError("VTP says no"), 422, "provider_rejected"),
        (ProviderRequestError("missing order_payment"), 422, "invalid_provider_request"),
        (ProviderAuthError(f"token {SECRET_TOKEN} rejected"), 502, "provider_auth_failed"),
    ],
)
def test_quote_provider_errors_are_mapped_safely(env, exc, status, code):
    client, provider, _ = env
    provider.fail_with["calculate_fee"] = exc
    body = {k: v for k, v in create_body().items() if k != "order_id"}
    response = client.post(f"{BASE}/quote", json=body, headers={"X-Request-ID": "req-1"})
    assert response.status_code == status
    assert response.json()["error"] == code
    assert response.json()["request_id"] == "req-1"
    assert SECRET_TOKEN not in response.text
    assert "Traceback" not in response.text


def test_provider_without_adapter_is_404(env):
    client, _, _ = env
    body = {k: v for k, v in create_body(provider="GHN").items() if k != "order_id"}
    response = client.post(f"{BASE}/quote", json=body)
    assert response.status_code == 404
    assert response.json()["error"] == "provider_not_supported"


def test_invalid_body_is_422(env):
    client, _, _ = env
    assert client.post(f"{BASE}/shipments", json=create_body(packages=[])).status_code == 422
    assert client.post(f"{BASE}/shipments", json=create_body(unknown=1)).status_code == 422
    bad_money = create_body(cod_amount={"amount": 1.5})
    assert client.post(f"{BASE}/shipments", json=bad_money).status_code == 422


def test_create_persists_and_audits(env):
    client, provider, sessions = env
    response = client.post(
        f"{BASE}/shipments", json=create_body(), headers={"X-Request-ID": "req-create"}
    )
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["status"] == "CREATED"
    assert view["tracking_number"] == "TRK0001"
    assert Decimal(view["cod_amount"]["amount"]) == Decimal(150000)
    assert Decimal(view["fee"]["amount"]) == Decimal(16500)
    assert view["requires_review"] is False
    assert audit_actions(sessions, view["id"]) == ["SHIPMENT_CREATED", "PROVIDER_CREATE_SUCCEEDED"]
    with sessions() as s:
        ids = {r.request_id for r in s.scalars(select(ShippingAuditLog))}
    assert ids == {"req-create"}

    by_id = client.get(f"{BASE}/shipments/{view['id']}").json()
    by_tracking = client.get(f"{BASE}/shipments/by-tracking/TRK0001").json()
    assert by_id == by_tracking == view
    scoped = client.get(f"{BASE}/shipments/by-tracking/TRK0001?provider=VIETTEL_POST")
    assert scoped.status_code == 200


def test_not_found(env):
    client, _, _ = env
    assert client.get(f"{BASE}/shipments/999").json()["error"] == "shipment_not_found"
    assert client.get(f"{BASE}/shipments/999").status_code == 404
    assert client.get(f"{BASE}/shipments/by-tracking/NOPE").status_code == 404


def test_duplicate_active_order_is_rejected_before_calling_provider(env):
    client, provider, _ = env
    assert client.post(f"{BASE}/shipments", json=create_body()).status_code == 201
    response = client.post(f"{BASE}/shipments", json=create_body())
    assert response.status_code == 409
    assert response.json()["error"] == "duplicate_active_shipment"
    assert provider.calls.count("create_shipment") == 1


def test_rejected_create_frees_the_order(env):
    client, provider, sessions = env
    provider.fail_with["create_shipment"] = ProviderRejectedError("bad address")
    response = client.post(f"{BASE}/shipments", json=create_body())
    assert response.status_code == 422
    with sessions() as s:
        (row,) = s.scalars(select(ShipmentRecord)).all()
    assert row.status == "DRAFT"
    assert audit_actions(sessions, row.id) == ["SHIPMENT_CREATED", "PROVIDER_CREATE_REJECTED"]
    del provider.fail_with["create_shipment"]
    assert client.post(f"{BASE}/shipments", json=create_body()).status_code == 201


def test_unknown_outcome_keeps_order_blocked(env):
    client, provider, sessions = env
    provider.fail_with["create_shipment"] = ProviderTimeoutError("t")
    response = client.post(f"{BASE}/shipments", json=create_body())
    assert response.status_code == 504
    with sessions() as s:
        (row,) = s.scalars(select(ShipmentRecord)).all()
    assert row.status == "READY_TO_CREATE"
    assert audit_actions(sessions, row.id)[-1] == "PROVIDER_OUTCOME_UNKNOWN"
    del provider.fail_with["create_shipment"]
    assert client.post(f"{BASE}/shipments", json=create_body()).status_code == 409


def test_cancel(env):
    client, provider, sessions = env
    shipment = client.post(f"{BASE}/shipments", json=create_body()).json()
    response = client.post(
        f"{BASE}/shipments/{shipment['id']}/cancel", json={"reason": "khách huỷ"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert audit_actions(sessions, shipment["id"])[-1] == "SHIPMENT_CANCELLED"
    again = client.post(f"{BASE}/shipments/{shipment['id']}/cancel")
    assert again.status_code == 409
    # the order is free again after cancellation
    assert client.post(f"{BASE}/shipments", json=create_body()).status_code == 201


def test_cancel_provider_failure_keeps_status(env):
    client, provider, sessions = env
    shipment = client.post(f"{BASE}/shipments", json=create_body()).json()
    provider.fail_with["cancel_shipment"] = ProviderUnavailableError("down")
    response = client.post(f"{BASE}/shipments/{shipment['id']}/cancel")
    assert response.status_code == 503
    assert status_of(sessions, shipment["id"]) == "CREATED"
    assert audit_actions(sessions, shipment["id"])[-1] == "PROVIDER_CANCEL_FAILED"


def test_cancel_unknown_shipment(env):
    client, _, _ = env
    assert client.post(f"{BASE}/shipments/424242/cancel").status_code == 404


def test_concurrent_creates_for_one_order(env, migrated_url):
    """Two simultaneous create requests: one 201, one 409, one provider call."""
    client, provider, _ = env
    provider.delay = 0.2
    results = []
    lock = threading.Lock()
    start = threading.Barrier(2)

    def post():
        start.wait()
        status = client.post(f"{BASE}/shipments", json=create_body()).status_code
        with lock:
            results.append(status)

    threads = [threading.Thread(target=post) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [201, 409]
    assert provider.calls.count("create_shipment") == 1


def test_request_id_is_sanitized(env):
    client, _, _ = env
    response = client.get("/health", headers={"X-Request-ID": "x" * 200})
    assert len(response.headers["X-Request-ID"]) == 32


def test_provider_success_but_record_failure_is_loud(env, monkeypatch, caplog):
    client, provider, sessions = env
    application = app.dependency_overrides[get_application]()

    def boom(*args, **kwargs):
        raise RuntimeError("db down with 0900000000")

    monkeypatch.setattr(application, "_record_created", boom)
    response = client.post(f"{BASE}/shipments", json=create_body())
    assert response.status_code == 500
    assert response.json()["error"] == "persistence_failed_after_provider_success"
    assert "TRK0001" in response.json()["detail"]  # operator can reconcile
    assert "0900000000" not in response.text
    assert any("TRK0001" in r.getMessage() for r in caplog.records)
    with sessions() as s:
        (row,) = s.scalars(select(ShipmentRecord)).all()
    assert row.status == "READY_TO_CREATE"  # order stays blocked: no blind re-create


def test_openapi_lists_the_g06_endpoints(env):
    client, _, _ = env
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/health",
        "/api/v1/shipping/providers",
        "/api/v1/shipping/quote",
        "/api/v1/shipping/shipments",
        "/api/v1/shipping/shipments/{shipment_id}",
        "/api/v1/shipping/shipments/by-tracking/{tracking_number}",
        "/api/v1/shipping/shipments/{shipment_id}/cancel",
    } <= paths


def test_application_layer_is_provider_neutral():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    for rel in ("services/shipping_app.py", "api/shipping.py", "api/schemas.py", "api/errors.py"):
        text = (root / rel).read_text(encoding="utf-8").lower()
        assert "viettel" not in text and "vtp" not in text, rel
