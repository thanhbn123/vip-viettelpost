"""G10 COD / fee / reconciliation foundation over a real migrated database."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_finance, get_operations
from app.main import app
from app.services.finance import ShipmentFinance
from app.services.operations import ShipmentOperations
from tests.integration.test_shipping_api import BASE, create_body
from tests.integration.test_webhook_to_shipment import make_env  # noqa: F401


@pytest.fixture
def fin(make_env):
    env = make_env()
    app.dependency_overrides[get_finance] = lambda: ShipmentFinance(env.sessions)
    app.dependency_overrides[get_operations] = lambda: ShipmentOperations(env.sessions)
    with TestClient(app) as client:
        yield env, client


def ship(client, order_id="ORD-F", cod="150000"):
    body = create_body(order_id=order_id)
    if cod is None:
        body.pop("cod_amount")
    else:
        body["cod_amount"] = {"amount": cod}
    response = client.post(f"{BASE}/shipments", json=body)
    assert response.status_code == 201
    return response.json()["id"]


def D(value):
    return Decimal(str(value))


def test_initial_finance_view(fin):
    _, client = fin
    sid = ship(client)
    view = client.get(f"{BASE}/shipments/{sid}/finance").json()
    assert D(view["cod_expected"]) == D("150000") and view["cod_status"] == "PENDING"
    assert view["cod_collected"] is None and view["actual_fee"] is None
    assert D(view["estimated_fee"]) == D("16500")  # fee quoted by the provider at creation


def test_cod_collected_and_remitted(fin):
    _, client = fin
    sid = ship(client)
    partial = client.post(f"{BASE}/shipments/{sid}/cod/collected", json={"amount": {"amount": "100000"}})
    assert partial.status_code == 200 and partial.json()["cod_status"] == "PARTIAL"
    full = client.post(f"{BASE}/shipments/{sid}/cod/collected", json={"amount": {"amount": "150000"}})
    assert full.json()["cod_status"] == "COLLECTED"
    remitted = client.post(
        f"{BASE}/shipments/{sid}/cod/remitted",
        json={"amount": {"amount": "150000"}, "reference": "SK-2026-09-001"},
    )
    view = remitted.json()
    assert view["cod_status"] == "REMITTED" and view["remittance_reference"] == "SK-2026-09-001"
    again = client.post(f"{BASE}/shipments/{sid}/cod/collected", json={"amount": {"amount": "1"}})
    assert again.status_code == 409
    audit = [a["action"] for a in client.get(f"{BASE}/shipments/{sid}/audit").json()]
    assert audit.count("COD_CHANGED") == 3


def test_cod_rules(fin):
    _, client = fin
    no_cod = ship(client, order_id="ORD-NOCOD", cod=None)
    r = client.post(f"{BASE}/shipments/{no_cod}/cod/collected", json={"amount": {"amount": "1"}})
    assert r.status_code == 422 and r.json()["error"] == "invalid_finance_operation"
    sid = ship(client)
    early = client.post(
        f"{BASE}/shipments/{sid}/cod/remitted", json={"amount": {"amount": "1"}, "reference": "X"}
    )
    assert early.status_code == 409  # nothing collected yet
    usd = client.post(
        f"{BASE}/shipments/{sid}/cod/collected", json={"amount": {"amount": "1", "currency": "USD"}}
    )
    assert usd.status_code == 422
    floaty = client.post(f"{BASE}/shipments/{sid}/cod/collected", json={"amount": {"amount": 1.5}})
    assert floaty.status_code == 422
    assert client.post(f"{BASE}/shipments/999/cod/collected", json={"amount": {"amount": "1"}}).status_code == 404


def test_fees_actual_and_adjustment(fin):
    _, client = fin
    sid = ship(client)
    actual = client.post(
        f"{BASE}/shipments/{sid}/fees",
        json={"fee_type": "SHIPPING", "source": "PROVIDER_ACTUAL", "amount": "17000.50",
              "provider_reference": "BK-1"},
    )
    assert actual.status_code == 201 and D(actual.json()["actual_fee"]) == D("17000.50")
    no_note = client.post(
        f"{BASE}/shipments/{sid}/fees",
        json={"fee_type": "SHIPPING", "source": "ADJUSTMENT", "amount": "-500"},
    )
    assert no_note.status_code == 422
    adjusted = client.post(
        f"{BASE}/shipments/{sid}/fees",
        json={"fee_type": "SHIPPING", "source": "ADJUSTMENT", "amount": "-500.50",
              "note": "VTP giảm cước theo đối soát"},
    )
    view = adjusted.json()
    assert D(view["actual_fee"]) == D("16500.00")
    assert [(f["source"], D(f["amount"])) for f in view["fees"]] == [
        ("PROVIDER_ACTUAL", D("17000.50")),
        ("ADJUSTMENT", D("-500.50")),
    ]
    negative_total = client.post(
        f"{BASE}/shipments/{sid}/fees",
        json={"fee_type": "SHIPPING", "source": "ADJUSTMENT", "amount": "-99999", "note": "x"},
    )
    assert negative_total.status_code == 422
    negative_actual = client.post(
        f"{BASE}/shipments/{sid}/fees",
        json={"fee_type": "SHIPPING", "source": "PROVIDER_ACTUAL", "amount": "-1"},
    )
    assert negative_actual.status_code == 422
    too_precise = client.post(
        f"{BASE}/shipments/{sid}/fees",
        json={"fee_type": "SHIPPING", "source": "PROVIDER_ACTUAL", "amount": "1.001"},
    )
    assert too_precise.status_code == 422
    audit = [a["action"] for a in client.get(f"{BASE}/shipments/{sid}/audit").json()]
    assert "FEE_RECORDED" in audit and "RECONCILIATION_ADJUSTED" in audit


def test_reconciliation_matched_mismatch_resolve(fin):
    _, client = fin
    sid = ship(client)
    matched = client.post(
        f"{BASE}/shipments/{sid}/reconciliations",
        json={"kind": "COD", "actual_amount": {"amount": "150000"}, "statement_reference": "ST-1"},
    ).json()["reconciliations"][-1]
    assert matched["status"] == "MATCHED" and D(matched["difference_amount"]) == 0
    mismatch = client.post(
        f"{BASE}/shipments/{sid}/reconciliations",
        json={"kind": "FEE", "actual_amount": {"amount": "17000"}, "statement_reference": "ST-1"},
    ).json()["reconciliations"][-1]
    assert mismatch["status"] == "MISMATCH"
    assert D(mismatch["difference_amount"]) == D("500.00")  # 17000 - 16500
    resolved = client.post(
        f"{BASE}/reconciliations/{mismatch['id']}/resolve", json={"note": "Chấp nhận phụ phí"}
    )
    assert resolved.status_code == 200
    assert resolved.json()["reconciliations"][-1]["status"] == "RESOLVED"
    assert client.post(
        f"{BASE}/reconciliations/{matched['id']}/resolve", json={"note": "x"}
    ).status_code == 409
    assert client.post(f"{BASE}/reconciliations/9999/resolve", json={"note": "x"}).status_code == 404


def test_fee_reconciliation_needs_expected_fee(fin, monkeypatch):
    env, client = fin

    original = env.provider.create_shipment

    async def no_fee(request):
        result = await original(request)
        return result.model_copy(update={"fee": None})

    env.provider.create_shipment = no_fee
    sid = ship(client, order_id="ORD-NOFEE")
    r = client.post(
        f"{BASE}/shipments/{sid}/reconciliations",
        json={"kind": "FEE", "actual_amount": {"amount": "1"}},
    )
    assert r.status_code == 422
