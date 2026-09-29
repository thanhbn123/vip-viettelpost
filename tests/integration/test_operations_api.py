"""G09 operational API: listing, history, provider status visibility, review, notes."""

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_operations
from app.main import app
from app.services.operations import ShipmentOperations
from tests.integration.test_shipping_api import BASE, create_body
from tests.integration.test_webhook_to_shipment import HOOK, vtp


@pytest.fixture
def ops_env(make_env):
    env = make_env()
    app.dependency_overrides[get_operations] = lambda: ShipmentOperations(env.sessions)
    with TestClient(app) as client:
        yield env, client


def make(client, order_id):
    response = client.post(f"{BASE}/shipments", json=create_body(order_id=order_id))
    assert response.status_code == 201
    return response.json()


def test_list_filters_and_pagination(ops_env):
    env, client = ops_env
    a = make(client, "ORD-A")  # TRK0001
    b = make(client, "ORD-B")  # TRK0002
    client.post(f"{BASE}/shipments/{b['id']}/cancel")
    client.post(HOOK, content=vtp(999, "29/09/2026 10:00:00", number=a["tracking_number"]))

    page = client.get(f"{BASE}/shipments").json()
    assert page["total"] == 2 and [i["id"] for i in page["items"]] == [b["id"], a["id"]]
    assert "receiver" not in page["items"][0] and "sender" not in page["items"][0]

    cancelled = client.get(f"{BASE}/shipments", params={"status": "CANCELLED"}).json()
    assert [i["id"] for i in cancelled["items"]] == [b["id"]]
    both = client.get(f"{BASE}/shipments", params=[("status", "CANCELLED"), ("status", "CREATED")])
    assert both.json()["total"] == 2

    review = client.get(f"{BASE}/shipments", params={"requires_review": "true"}).json()
    assert [i["id"] for i in review["items"]] == [a["id"]] and review["items"][0]["requires_review"]
    assert client.get(f"{BASE}/shipments", params={"requires_review": "false"}).json()["total"] == 1

    assert client.get(f"{BASE}/shipments", params={"order_id": "ORD-A"}).json()["total"] == 1
    assert (
        client.get(f"{BASE}/shipments", params={"tracking_number": "TRK0002"}).json()["total"] == 1
    )
    assert client.get(f"{BASE}/shipments", params={"provider": "VIETTEL_POST"}).json()["total"] == 2
    assert client.get(f"{BASE}/shipments", params={"provider": "GHN"}).json()["total"] == 0

    first = client.get(f"{BASE}/shipments", params={"limit": 1}).json()
    second = client.get(f"{BASE}/shipments", params={"limit": 1, "offset": 1}).json()
    assert first["items"][0]["id"] != second["items"][0]["id"] and first["total"] == 2
    assert client.get(f"{BASE}/shipments", params={"limit": 1000}).status_code == 422
    future = client.get(f"{BASE}/shipments", params={"created_from": "2999-01-01T00:00:00+00:00"})
    assert future.json()["total"] == 0
    assert (
        client.get(f"{BASE}/shipments", params={"created_from": "2026-01-01T00:00:00"}).status_code
        == 422
    )


def test_history_provider_status_and_audit(ops_env):
    env, client = ops_env
    s = make(client, "ORD-H")
    client.post(HOOK, content=vtp(200, "29/09/2026 10:00:00", number=s["tracking_number"]))
    client.post(HOOK, content=vtp(505, "29/09/2026 11:00:00", number=s["tracking_number"]))

    events = client.get(f"{BASE}/shipments/{s['id']}/events").json()
    assert [
        (e["canonical_status"], e["provider_status"], e["requires_review"]) for e in events
    ] == [
        ("PICKED", "200", False),
        (None, "505", True),
    ]
    assert events[1]["provider_status_name"] == "Yêu cầu chuyển hoàn"

    hooks = client.get(f"{BASE}/shipments/{s['id']}/webhook-events").json()
    assert [h["processing_status"] for h in hooks] == ["PROCESSED", "PROCESSED"]
    assert all("payload" not in h and "payload_json" not in h for h in hooks)

    audit = [a["action"] for a in client.get(f"{BASE}/shipments/{s['id']}/audit").json()]
    assert audit == ["SHIPMENT_CREATED", "PROVIDER_CREATE_SUCCEEDED", "STATUS_CHANGED_BY_PROVIDER"]


def test_operator_note(ops_env):
    env, client = ops_env
    s = make(client, "ORD-N")
    response = client.post(
        f"{BASE}/shipments/{s['id']}/notes",
        json={"text": "Đã gọi VTP xác nhận"},
        headers={"X-Request-ID": "note-1"},
    )
    assert response.status_code == 201
    note = response.json()
    assert (note["action"], note["reason"], note["request_id"]) == (
        "OPERATOR_NOTE",
        "Đã gọi VTP xác nhận",
        "note-1",
    )
    assert (
        client.get(f"{BASE}/shipments/{s['id']}").json()["status"] == "CREATED"
    )  # no state change
    assert client.post(f"{BASE}/shipments/{s['id']}/notes", json={"text": " "}).status_code == 422
    assert (
        client.post(f"{BASE}/shipments/{s['id']}/notes", json={"text": "x" * 501}).status_code
        == 422
    )


@pytest.mark.parametrize("suffix", ["events", "webhook-events", "audit"])
def test_unknown_shipment_is_404(ops_env, suffix):
    _, client = ops_env
    response = client.get(f"{BASE}/shipments/9999/{suffix}")
    assert response.status_code == 404 and response.json()["error"] == "shipment_not_found"
    assert client.post(f"{BASE}/shipments/9999/notes", json={"text": "x"}).status_code == 404
