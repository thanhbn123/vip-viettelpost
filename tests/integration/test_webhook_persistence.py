"""Durable webhook idempotency on shipping_webhook_events (SQLite; PostgreSQL if configured)."""

import json
import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import ShippingWebhookEvent
from app.db.session import make_engine, make_session_factory
from app.main import app
from app.providers.viettel_post.events import resolve_timezone
from app.webhooks.dependencies import get_vtp_webhook_processor
from app.webhooks.processor import WebhookProcessor, WebhookResultKind
from app.webhooks.sql_sink import SqlWebhookSink
from app.webhooks.stores import IngestResult

SECRET = "test-webhook-secret-not-real"
URL = "/api/v1/shipping/webhooks/viettel-post"
NOW = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)


def payload(status=200, date="10/11/2025 11:07:16", number="TESTVTP0000000001"):
    return {
        "DATA": {
            "ORDER_NUMBER": number,
            "ORDER_REFERENCE": "VIP-ORDER-1",
            "ORDER_STATUSDATE": date,
            "ORDER_STATUS": status,
            "RECEIVER_FULLNAME": "Người nhận Test",
            "EMPLOYEE_PHONE": "84000000000",
        },
        "TOKEN": SECRET,
    }


def body(p) -> bytes:
    return json.dumps(p, ensure_ascii=False).encode("utf-8")


@pytest.fixture
def factory(migrated_url):
    engine = make_engine(migrated_url)
    yield make_session_factory(engine)
    engine.dispose()


def processor(factory, **sink_kwargs):
    sink = SqlWebhookSink(factory, clock=lambda: NOW, **sink_kwargs)
    return WebhookProcessor(shared_secret=SECRET, sink=sink, clock=lambda: NOW)


def rows(factory) -> list[ShippingWebhookEvent]:
    with factory() as s:
        return list(s.scalars(select(ShippingWebhookEvent).order_by(ShippingWebhookEvent.id)))


def test_event_is_stored_durably_without_token(factory):
    outcome = processor(factory).process(body(payload()))
    assert outcome.kind is WebhookResultKind.ACCEPTED
    (row,) = rows(factory)
    assert row.processing_status == "RECEIVED"
    assert row.attempt_count == 1
    assert row.tracking_number == "TESTVTP0000000001"
    assert row.order_id == "VIP-ORDER-1"
    assert row.provider_status == "200"
    assert row.canonical_status == "PICKED"
    assert row.requires_review is False
    assert row.fingerprint_basis == "provider+tracking+status+status_date"
    assert row.occurred_at is None  # timezone not configured: never guessed
    assert row.occurred_at_raw == "10/11/2025 11:07:16"
    assert row.received_at is not None
    stored = json.dumps(row.payload_json, ensure_ascii=False)
    assert "TOKEN" not in stored and SECRET not in stored
    assert row.payload_json["ORDER_STATUS"] == 200


def test_configured_timezone_gives_aware_time(factory):
    p = processor(factory, event_timezone=resolve_timezone("Asia/Ho_Chi_Minh"))
    p.process(body(payload()))
    (row,) = rows(factory)
    expected = datetime(2025, 11, 10, 11, 7, 16, tzinfo=timezone(timedelta(hours=7)))
    assert row.occurred_at == expected
    assert row.occurred_at.utcoffset() == timedelta(0)  # stored/returned as UTC


def test_duplicate_is_acked_and_stored_once(factory):
    p = processor(factory)
    assert p.process(body(payload())).kind is WebhookResultKind.ACCEPTED
    assert p.process(body(payload())).kind is WebhookResultKind.DUPLICATE
    # a different processor instance (another worker / after restart) also sees it
    assert processor(factory).process(body(payload())).kind is WebhookResultKind.DUPLICATE
    assert len(rows(factory)) == 1


def test_unknown_status_is_stored_for_review(factory):
    processor(factory).process(body(payload(status=999)))
    (row,) = rows(factory)
    assert row.canonical_status is None
    assert row.requires_review is True
    assert row.provider_status == "999"


def test_failure_rolls_back_is_recorded_and_retry_reprocesses(factory):
    calls = {"n": 0}

    def flaky(session, row, event):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom with 0900000000 personal data")

    p = processor(factory, after_store=flaky)
    with pytest.raises(RuntimeError):
        p.process(body(payload()))
    (row,) = rows(factory)
    assert row.processing_status == "FAILED"
    assert row.error_code == "RuntimeError"
    assert "0900000000" not in (row.error_message or "")
    assert row.attempt_count == 1

    assert p.process(body(payload())).kind is WebhookResultKind.ACCEPTED  # VTP retry
    (row,) = rows(factory)
    assert row.processing_status == "RECEIVED"
    assert row.attempt_count == 2
    assert p.process(body(payload())).kind is WebhookResultKind.DUPLICATE


def test_sink_reports_retry(factory):
    sink = SqlWebhookSink(factory, clock=lambda: NOW)
    p = WebhookProcessor(shared_secret=SECRET, sink=sink)
    p.process(body(payload()))
    with factory() as s, s.begin():
        s.scalar(select(ShippingWebhookEvent)).processing_status = "FAILED"
    captured = {}
    original = sink.ingest

    def spy(event):
        captured["result"] = original(event)
        return captured["result"]

    sink.ingest = spy
    p.process(body(payload()))
    assert captured["result"] is IngestResult.RETRIED


def test_concurrent_duplicate_deliveries_are_stored_once(factory):
    """Eight simultaneous deliveries of one event: one NEW, seven DUPLICATE, one row."""
    p = processor(factory)
    start = threading.Barrier(8)
    results = []
    lock = threading.Lock()

    def deliver():
        start.wait()
        outcome = p.process(body(payload()))
        with lock:
            results.append(outcome.kind)

    threads = [threading.Thread(target=deliver) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == sorted(
        [WebhookResultKind.ACCEPTED] + [WebhookResultKind.DUPLICATE] * 7
    )
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(ShippingWebhookEvent)) == 1


def test_route_end_to_end_with_durable_sink(factory):
    app.dependency_overrides[get_vtp_webhook_processor] = lambda: processor(factory)
    try:
        with TestClient(app) as client:
            first = client.post(URL, content=body(payload()))
            second = client.post(URL, content=body(payload()))
            bad = client.post(URL, content=body({**payload(), "TOKEN": "wrong"}))
    finally:
        app.dependency_overrides.clear()
    assert (first.status_code, first.json()["result"]) == (200, "ACCEPTED")
    assert (second.status_code, second.json()["result"]) == (200, "DUPLICATE")
    assert bad.status_code == 401
    assert len(rows(factory)) == 1
