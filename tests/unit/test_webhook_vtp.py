"""Viettel Post webhook pipeline tests. No network, no database."""

import copy
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.domain.models.shipment import ShipmentStatus
from app.main import app
from app.webhooks.dependencies import get_vtp_webhook_processor
from app.webhooks.fingerprint import FingerprintBasis, build_fingerprint
from app.webhooks.processor import WebhookProcessor, WebhookResultKind
from app.webhooks.stores import InMemoryIdempotencyStore, InMemoryWebhookEventStore
from app.webhooks.viettel_post_payload import RejectionKind

SECRET = "test-webhook-secret-not-real"  # test value only
URL = "/api/v1/shipping/webhooks/viettel-post"


def vtp_payload(**data_overrides):
    """Shape follows the official sample at https://partner2.viettelpost.vn/document/webhook."""
    data = {
        "ORDER_NUMBER": "TESTVTP0000000001",
        "ORDER_REFERENCE": "VIP-ORDER-1",
        "ORDER_STATUSDATE": "10/11/2025 11:07:16",
        "ORDER_STATUS": 200,
        "STATUS_NAME": "Lấy hàng thành công",
        "LOCATION_CURRENTLY": "HNI, Bưu cục test",
        "NOTE": "ghi chú",
        "MONEY_COLLECTION": 0,
        "EMPLOYEE_NAME": "Bưu tá Test",
        "EMPLOYEE_PHONE": "84000000000",
        "RECEIVER_FULLNAME": "Người nhận Test",
        "IS_RETURNING": False,
        "POD": {"IMAGES": []},
        "REASON_CODE": None,
    }
    data.update(data_overrides)
    return {"DATA": data, "TOKEN": SECRET}


def body(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.fixture
def stores():
    return InMemoryIdempotencyStore(), InMemoryWebhookEventStore()


@pytest.fixture
def processor(stores):
    idem, events = stores
    return WebhookProcessor(shared_secret=SECRET, idempotency_store=idem, event_store=events)


# --- valid / mapping -------------------------------------------------------------------


def test_valid_event_is_accepted_and_stored(processor, stores):
    outcome = processor.process(body(vtp_payload()))
    assert outcome.kind is WebhookResultKind.ACCEPTED
    assert outcome.http_status == 200
    assert outcome.event.canonical_status is ShipmentStatus.PICKED
    assert outcome.event.tracking_number == "TESTVTP0000000001"
    stored = stores[1].events
    assert len(stored) == 1
    assert stored[0].canonical_status is ShipmentStatus.PICKED
    assert stored[0].provider_event_time_raw == "10/11/2025 11:07:16"
    assert stored[0].provider_event_time is not None


def test_provider_status_preserved(processor, stores):
    outcome = processor.process(body(vtp_payload(ORDER_STATUS=501)))
    assert outcome.event.provider_status == "501"
    stored = stores[1].events[0]
    assert stored.provider_status == "501"
    assert stored.raw_data["ORDER_STATUS"] == 501
    assert stored.provider_status_name == "Thành công – Phát thành công"


def test_unknown_status_is_acked_preserved_and_flagged(processor, stores):
    outcome = processor.process(body(vtp_payload(ORDER_STATUS=999)))
    assert outcome.http_status == 200
    assert outcome.kind is WebhookResultKind.ACCEPTED
    assert outcome.event.is_known is False
    assert outcome.event.canonical_status is None
    assert outcome.event.canonical_status is not ShipmentStatus.IN_TRANSIT
    assert outcome.event.requires_review is True
    stored = stores[1].events[0]
    assert stored.provider_status == "999"
    assert stored.requires_review is True
    assert outcome.response_body() == {"result": "ACCEPTED", "status_known": False}


def test_known_unmapped_status_is_acked_without_canonical(processor):
    outcome = processor.process(body(vtp_payload(ORDER_STATUS=505)))
    assert outcome.http_status == 200
    assert outcome.event.is_known is True
    assert outcome.event.canonical_status is None
    assert outcome.event.requires_review is True


def test_numeric_string_status_is_accepted(processor):
    outcome = processor.process(body(vtp_payload(ORDER_STATUS="501")))
    assert outcome.event.canonical_status is ShipmentStatus.DELIVERED


# --- idempotency / replay --------------------------------------------------------------


def test_duplicate_webhook_is_acked_once_stored(processor, stores):
    first = processor.process(body(vtp_payload()))
    second = processor.process(body(vtp_payload()))
    assert first.kind is WebhookResultKind.ACCEPTED
    assert second.kind is WebhookResultKind.DUPLICATE
    assert second.http_status == 200
    assert len(stores[1].events) == 1


def test_replay_with_changed_volatile_fields_is_duplicate(processor, stores):
    processor.process(body(vtp_payload()))
    replay = vtp_payload(NOTE="khác", LOCATION_CURRENTLY="nơi khác", MONEY_COLLECTION=5)
    outcome = processor.process(body(replay))
    assert outcome.kind is WebhookResultKind.DUPLICATE
    assert len(stores[1].events) == 1


def test_same_status_at_different_time_is_a_new_event(processor, stores):
    processor.process(body(vtp_payload(ORDER_STATUS=506, ORDER_STATUSDATE="10/11/2025 11:00:00")))
    outcome = processor.process(
        body(vtp_payload(ORDER_STATUS=506, ORDER_STATUSDATE="11/11/2025 09:00:00"))
    )
    assert outcome.kind is WebhookResultKind.ACCEPTED
    assert len(stores[1].events) == 2


def test_replay_of_old_event_after_newer_ones_is_duplicate(processor, stores):
    old = vtp_payload(ORDER_STATUS=200, ORDER_STATUSDATE="10/11/2025 11:00:00")
    processor.process(body(old))
    processor.process(body(vtp_payload(ORDER_STATUS=501, ORDER_STATUSDATE="12/11/2025 15:00:00")))
    outcome = processor.process(body(old))
    assert outcome.kind is WebhookResultKind.DUPLICATE
    assert len(stores[1].events) == 2


def test_fingerprint_is_deterministic():
    data = vtp_payload()["DATA"]
    kwargs = {
        "provider": "VIETTEL_POST",
        "tracking_number": "TESTVTP0000000001",
        "provider_status": "200",
        "status_date_raw": "10/11/2025 11:07:16",
        "data": data,
    }
    a = build_fingerprint(**kwargs)
    b = build_fingerprint(**{**kwargs, "data": {**data, "NOTE": "x"}})
    assert a == b
    assert a.basis is FingerprintBasis.STATUS_TRANSITION
    assert len(a.value) == 64
    assert build_fingerprint(**{**kwargs, "provider_status": "501"}) != a
    assert build_fingerprint(**{**kwargs, "tracking_number": "OTHER"}) != a
    assert build_fingerprint(**{**kwargs, "status_date_raw": "10/11/2025 11:07:17"}) != a


def test_fingerprint_fallback_without_status_date_is_deterministic():
    data = copy.deepcopy(vtp_payload()["DATA"])
    del data["ORDER_STATUSDATE"]
    kwargs = {
        "provider": "VIETTEL_POST",
        "tracking_number": "TESTVTP0000000001",
        "provider_status": "200",
        "status_date_raw": None,
    }
    a = build_fingerprint(**kwargs, data=data)
    b = build_fingerprint(**kwargs, data=dict(reversed(list(data.items()))))
    assert a == b
    assert a.basis is FingerprintBasis.FULL_DATA


def test_fingerprint_fallback_separates_two_delivery_attempts_of_one_status():
    """Regression (CR-READY-002, reverted): narrowing the fallback merged these two.

    Without ORDER_STATUSDATE the only thing telling two real delivery attempts apart is
    a 'volatile' field. Merging them drops the second as DUPLICATE — silent event loss.
    """
    data = copy.deepcopy(vtp_payload()["DATA"])
    del data["ORDER_STATUSDATE"]
    kwargs = {
        "provider": "VIETTEL_POST",
        "tracking_number": "TESTVTP0000000001",
        "provider_status": "103",
        "status_date_raw": None,
    }
    first = build_fingerprint(**kwargs, data={**data, "LOCATION_CURRENTLY": "BC Cau Giay"})
    second = build_fingerprint(**kwargs, data={**data, "LOCATION_CURRENTLY": "BC Ben Thanh"})
    assert first != second
    assert first.basis is FingerprintBasis.FULL_DATA


def test_storage_failure_releases_claim_so_retry_is_processed(stores):
    idem, events = stores

    class FailingOnce:
        calls = 0

        def append(self, event):
            FailingOnce.calls += 1
            if FailingOnce.calls == 1:
                raise RuntimeError("db down")
            events.append(event)

    p = WebhookProcessor(shared_secret=SECRET, idempotency_store=idem, event_store=FailingOnce())
    with pytest.raises(RuntimeError):
        p.process(body(vtp_payload()))
    retry = p.process(body(vtp_payload()))
    assert retry.kind is WebhookResultKind.ACCEPTED
    assert len(events.events) == 1


# --- validation ------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [b"{not json", b"", b"\xff\xfe", b'{"DATA": '])
def test_malformed_json_is_rejected(processor, raw):
    outcome = processor.process(raw)
    assert outcome.http_status == 400
    assert outcome.rejection is RejectionKind.MALFORMED_JSON


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        ([], RejectionKind.INVALID_PAYLOAD),
        ({"TOKEN": SECRET}, RejectionKind.MISSING_FIELD),
        ({"DATA": "x", "TOKEN": SECRET}, RejectionKind.INVALID_PAYLOAD),
    ],
)
def test_invalid_structure_is_rejected(processor, payload, kind):
    outcome = processor.process(body(payload))
    assert outcome.http_status == 400
    assert outcome.rejection is kind


def test_missing_tracking_number_is_rejected(processor, stores):
    payload = vtp_payload()
    del payload["DATA"]["ORDER_NUMBER"]
    outcome = processor.process(body(payload))
    assert outcome.http_status == 400
    assert outcome.rejection is RejectionKind.MISSING_FIELD
    assert stores[1].events == []


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_tracking_number_is_rejected(processor, value):
    outcome = processor.process(body(vtp_payload(ORDER_NUMBER=value)))
    assert outcome.rejection is RejectionKind.MISSING_FIELD


@pytest.mark.parametrize("value", [12345, "ABC 123", "ABC\n123", "A" * 129, ["x"]])
def test_invalid_tracking_number_is_rejected(processor, value):
    outcome = processor.process(body(vtp_payload(ORDER_NUMBER=value)))
    assert outcome.http_status == 400
    assert outcome.rejection is RejectionKind.INVALID_TRACKING_NUMBER


def test_missing_status_is_rejected(processor):
    payload = vtp_payload()
    del payload["DATA"]["ORDER_STATUS"]
    outcome = processor.process(body(payload))
    assert outcome.rejection is RejectionKind.MISSING_FIELD


@pytest.mark.parametrize("value", [True, 5.01, -1, "DELIVERED", {"x": 1}])
def test_malformed_status_is_rejected_not_treated_as_unknown(processor, value):
    outcome = processor.process(body(vtp_payload(ORDER_STATUS=value)))
    assert outcome.http_status == 400
    assert outcome.rejection is RejectionKind.INVALID_STATUS_FORMAT


def test_oversized_body_is_rejected(stores):
    idem, events = stores
    p = WebhookProcessor(
        shared_secret=SECRET, idempotency_store=idem, event_store=events, max_body_bytes=100
    )
    outcome = p.process(body(vtp_payload()))
    assert outcome.http_status == 413


# --- authentication --------------------------------------------------------------------


def test_invalid_token_is_rejected(processor, stores):
    payload = vtp_payload()
    payload["TOKEN"] = "wrong"
    outcome = processor.process(body(payload))
    assert outcome.http_status == 401
    assert outcome.rejection is RejectionKind.UNAUTHORIZED
    assert stores[1].events == []


@pytest.mark.parametrize("token", [None, "", 123])
def test_missing_token_is_rejected(processor, token):
    payload = vtp_payload()
    payload["TOKEN"] = token
    outcome = processor.process(body(payload))
    assert outcome.http_status == 401


def test_auth_is_checked_before_idempotency(processor, stores):
    processor.process(body(vtp_payload()))
    forged = vtp_payload()
    forged["TOKEN"] = "wrong"
    outcome = processor.process(body(forged))
    assert outcome.http_status == 401


def test_unconfigured_secret_fails_closed(stores):
    idem, events = stores
    p = WebhookProcessor(shared_secret=None, idempotency_store=idem, event_store=events)
    outcome = p.process(body(vtp_payload()))
    assert outcome.http_status == 503
    assert events.events == []


def test_no_unsupported_authentication_assumption():
    """No HMAC/signature scheme is documented by Viettel Post, so none is enforced.

    Only the documented body TOKEN decides; headers are not trusted or required.
    """
    import app.webhooks.processor as proc_module

    with open(proc_module.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "hmac.new" not in source  # no invented HMAC signature
    assert "headers" not in source  # no header-based auth assumption in the pipeline

    idem, events = InMemoryIdempotencyStore(), InMemoryWebhookEventStore()
    p = WebhookProcessor(shared_secret=SECRET, idempotency_store=idem, event_store=events)
    app.dependency_overrides[get_vtp_webhook_processor] = lambda: p
    try:
        client = TestClient(app)
        # No Authorization header, no signature header: valid TOKEN is enough.
        ok = client.post(URL, content=body(vtp_payload()))
        # A made-up signature header does not rescue a wrong TOKEN.
        forged = vtp_payload(ORDER_STATUS=501)
        forged["TOKEN"] = "wrong"
        bad = client.post(URL, content=body(forged), headers={"X-Signature": "anything"})
    finally:
        app.dependency_overrides.clear()
    assert ok.status_code == 200
    assert bad.status_code == 401


def test_stored_event_never_contains_token(processor, stores):
    processor.process(body(vtp_payload()))
    stored = stores[1].events[0]
    assert "TOKEN" not in stored.raw_data
    assert SECRET not in repr(stored)


def test_secret_and_pii_not_logged(processor, caplog):
    caplog.set_level(logging.DEBUG, logger="app.webhooks.viettel_post")
    processor.process(body(vtp_payload()))
    processor.process(body(vtp_payload()))
    processor.process(body(vtp_payload(ORDER_STATUS=999, ORDER_STATUSDATE="1/1/2026 00:00:00")))
    bad = vtp_payload()
    bad["TOKEN"] = "wrong-token-value"
    processor.process(body(bad))
    text = caplog.text
    assert caplog.records
    for secret_or_pii in (SECRET, "wrong-token-value", "Người nhận Test", "84000000000"):
        assert secret_or_pii not in text


# --- HTTP route ------------------------------------------------------------------------


@pytest.fixture
def client(processor):
    app.dependency_overrides[get_vtp_webhook_processor] = lambda: processor
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_route_valid_duplicate_unknown_malformed(client):
    assert client.post(URL, content=body(vtp_payload())).json() == {
        "result": "ACCEPTED",
        "status_known": True,
    }
    dup = client.post(URL, content=body(vtp_payload()))
    assert dup.status_code == 200
    assert dup.json()["result"] == "DUPLICATE"
    unknown = client.post(URL, content=body(vtp_payload(ORDER_STATUS=999)))
    assert unknown.status_code == 200
    assert client.post(URL, content=b"{oops").status_code == 400


def test_route_response_does_not_echo_payload(client):
    response = client.post(URL, content=body(vtp_payload()))
    text = response.text
    assert SECRET not in text
    assert "TESTVTP0000000001" not in text
    assert "Người nhận Test" not in text


def test_route_rejects_declared_oversized_body(client):
    response = client.post(URL, content=b"{}", headers={"content-length": str(10**7)})
    assert response.status_code == 413
