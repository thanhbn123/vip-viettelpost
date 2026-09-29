"""G07: Viettel Post webhook -> TOKEN -> durable claim -> raw event -> mapping ->
shipment update -> shipment event -> audit -> ACK, over a real migrated database."""

import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.dependencies import get_application
from app.db.models import Shipment as ShipmentRecord
from app.db.models import ShipmentEvent as EventRecord
from app.db.models import ShippingAuditLog, ShippingWebhookEvent
from app.db.session import make_engine, make_session_factory
from app.domain.models import ShippingProviderCode
from app.main import app
from app.providers.viettel_post.events import resolve_timezone, vtp_event_order_key
from app.services.shipping_app import ShippingApplication
from app.services.webhook_applier import WebhookShipmentApplier
from app.webhooks.dependencies import get_vtp_webhook_processor
from app.webhooks.processor import WebhookProcessor
from app.webhooks.sql_sink import SqlWebhookSink
from tests.integration.test_shipping_api import BASE, FakeProvider, create_body

SECRET = "test-webhook-secret-not-real"
HOOK = "/api/v1/shipping/webhooks/viettel-post"


def vtp(status, date, number="TRK0001", token=SECRET):
    return json.dumps(
        {
            "DATA": {
                "ORDER_NUMBER": number,
                "ORDER_STATUS": status,
                "ORDER_STATUSDATE": date,
                "RECEIVER_FULLNAME": "Người nhận",
            },
            "TOKEN": token,
        },
        ensure_ascii=False,
    ).encode("utf-8")


class Env:
    def __init__(self, url, *, timezone=None, fail_hook=None):
        self.engine = make_engine(url)
        self.sessions = make_session_factory(self.engine)
        self.provider = FakeProvider()
        self.applier = WebhookShipmentApplier(event_order_key=vtp_event_order_key)
        hook = self.applier
        if fail_hook is not None:

            def hook(session, row, event):
                fail_hook()
                self.applier(session, row, event)

        self.processor = WebhookProcessor(
            shared_secret=SECRET,
            sink=SqlWebhookSink(
                self.sessions, event_timezone=resolve_timezone(timezone), after_store=hook
            ),
        )
        self.app = ShippingApplication(
            {ShippingProviderCode.VIETTEL_POST: self.provider},
            self.sessions,
            webhook_applier=self.applier,
        )

    def shipment(self, sid):
        with self.sessions() as s:
            return s.get(ShipmentRecord, sid)

    def events(self, sid):
        with self.sessions() as s:
            return list(
                s.scalars(
                    select(EventRecord)
                    .where(EventRecord.shipment_id == sid)
                    .order_by(EventRecord.id)
                )
            )

    def webhooks(self):
        with self.sessions() as s:
            return list(s.scalars(select(ShippingWebhookEvent).order_by(ShippingWebhookEvent.id)))


@pytest.fixture
def make_env(migrated_url):
    envs = []

    def build(**kwargs):
        env = Env(migrated_url, **kwargs)
        envs.append(env)
        app.dependency_overrides[get_application] = lambda: env.app
        app.dependency_overrides[get_vtp_webhook_processor] = lambda: env.processor
        return env

    yield build
    app.dependency_overrides.clear()
    for env in envs:
        env.engine.dispose()


@pytest.fixture
def env(make_env):
    return make_env()


@pytest.fixture
def client(env):
    with TestClient(app) as c:
        yield c


def created(client):
    response = client.post(f"{BASE}/shipments", json=create_body())
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_mapped_status_updates_shipment_event_and_audit(env, client):
    sid = created(client)
    response = client.post(HOOK, content=vtp(200, "29/09/2026 10:00:00"))
    assert response.status_code == 200 and response.json()["result"] == "ACCEPTED"
    shipment = env.shipment(sid)
    assert (shipment.status, shipment.provider_status) == ("PICKED", "200")
    (event,) = env.events(sid)
    assert event.canonical_status == "PICKED" and event.requires_review is False
    (hook,) = env.webhooks()
    assert hook.processing_status == "PROCESSED" and hook.shipment_id == sid
    assert event.webhook_event_id == hook.id and event.provider_event_id == hook.fingerprint
    with env.sessions() as s:
        actions = [
            a.action for a in s.scalars(select(ShippingAuditLog).order_by(ShippingAuditLog.id))
        ]
    assert actions[-1] == "STATUS_CHANGED_BY_PROVIDER"
    view = client.get(f"{BASE}/shipments/{sid}").json()
    assert view["status"] == "PICKED" and view["events"][0]["provider_status"] == "200"


def test_unknown_status_is_recorded_for_review_without_moving_shipment(env, client):
    sid = created(client)
    client.post(HOOK, content=vtp(999, "29/09/2026 10:00:00"))
    assert env.shipment(sid).status == "CREATED"
    (event,) = env.events(sid)
    assert event.canonical_status is None and event.requires_review is True
    assert client.get(f"{BASE}/shipments/{sid}").json()["requires_review"] is True


def test_duplicate_event_applies_once(env, client):
    sid = created(client)
    for _ in range(3):
        assert client.post(HOOK, content=vtp(200, "29/09/2026 10:00:00")).status_code == 200
    assert len(env.events(sid)) == 1 and len(env.webhooks()) == 1


def test_concurrent_duplicate_deliveries_apply_once(env, client):
    sid = created(client)
    start = threading.Barrier(6)
    codes = []
    lock = threading.Lock()

    def deliver():
        start.wait()
        outcome = env.processor.process(vtp(500, "29/09/2026 11:00:00"))
        with lock:
            codes.append(outcome.kind.value)

    threads = [threading.Thread(target=deliver) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(codes) == ["ACCEPTED"] + ["DUPLICATE"] * 5
    assert len(env.events(sid)) == 1
    assert env.shipment(sid).status == "OUT_FOR_DELIVERY"


def test_malformed_and_unauthenticated_are_rejected_without_side_effects(env, client):
    sid = created(client)
    assert client.post(HOOK, content=b"{not json").status_code == 400
    assert (
        client.post(HOOK, content=vtp(200, "29/09/2026 10:00:00", token="wrong")).status_code == 401
    )
    assert env.webhooks() == [] and env.events(sid) == []
    assert env.shipment(sid).status == "CREATED"


def test_persistence_failure_rolls_back_and_retry_applies(make_env):
    state = {"fail": True}

    def maybe_fail():
        if state["fail"]:
            raise RuntimeError("db hiccup")

    env = make_env(fail_hook=maybe_fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        sid = created(client)
        first = client.post(HOOK, content=vtp(200, "29/09/2026 10:00:00"))
        assert first.status_code == 500
        assert env.shipment(sid).status == "CREATED" and env.events(sid) == []
        (hook,) = env.webhooks()
        assert hook.processing_status == "FAILED"
        state["fail"] = False
        retry = client.post(HOOK, content=vtp(200, "29/09/2026 10:00:00"))
        assert retry.status_code == 200 and retry.json()["result"] == "ACCEPTED"
    assert env.shipment(sid).status == "PICKED" and len(env.events(sid)) == 1
    (hook,) = env.webhooks()
    assert (hook.processing_status, hook.attempt_count) == ("PROCESSED", 2)


def test_event_before_shipment_is_replayed_when_shipment_is_recorded(env, client):
    # Viettel Post can call back before our create request has recorded the tracking number.
    client.post(HOOK, content=vtp(103, "29/09/2026 09:00:00"))
    (hook,) = env.webhooks()
    assert (hook.processing_status, hook.error_code) == ("IGNORED", "SHIPMENT_NOT_FOUND")
    sid = created(client)  # fake provider returns TRK0001
    assert env.shipment(sid).status == "READY_TO_PICK"
    (hook,) = env.webhooks()
    assert hook.processing_status == "PROCESSED" and hook.shipment_id == sid
    # a redelivery of the same event is still a duplicate
    assert (
        client.post(HOOK, content=vtp(103, "29/09/2026 09:00:00")).json()["result"] == "DUPLICATE"
    )


def test_terminal_status_is_never_left_by_webhook(env, client):
    sid = created(client)
    client.post(HOOK, content=vtp(501, "29/09/2026 12:00:00"))
    client.post(HOOK, content=vtp(506, "29/09/2026 13:00:00"))
    assert env.shipment(sid).status == "DELIVERED"
    late = env.events(sid)[-1]
    assert late.requires_review is True and late.metadata_json == {
        "decision": "AFTER_TERMINAL_STATUS"
    }


def test_out_of_order_event_does_not_regress_status(env, client):
    sid = created(client)
    client.post(HOOK, content=vtp(500, "29/09/2026 12:00:00"))  # OUT_FOR_DELIVERY
    client.post(HOOK, content=vtp(300, "29/09/2026 08:00:00"))  # older IN_TRANSIT, late
    assert env.shipment(sid).status == "OUT_FOR_DELIVERY"
    assert env.events(sid)[-1].metadata_json == {"decision": "OUT_OF_ORDER"}
    client.post(HOOK, content=vtp(501, "29/09/2026 15:00:00"))
    assert env.shipment(sid).status == "DELIVERED"


def test_configured_timezone_orders_by_aware_time(make_env):
    env = make_env(timezone="Asia/Ho_Chi_Minh")
    with TestClient(app) as client:
        sid = created(client)
        client.post(HOOK, content=vtp(500, "29/09/2026 12:00:00"))
        client.post(HOOK, content=vtp(300, "29/09/2026 08:00:00"))
    assert env.shipment(sid).status == "OUT_FOR_DELIVERY"
    assert all(e.occurred_at is not None for e in env.events(sid))


def test_cancelled_via_api_then_provider_confirms(env, client):
    sid = created(client)
    client.post(f"{BASE}/shipments/{sid}/cancel")
    client.post(HOOK, content=vtp(107, "29/09/2026 10:00:00"))  # VTP "partner requested cancel"
    assert env.shipment(sid).status == "CANCELLED"
    confirmation = env.events(sid)[-1]
    assert confirmation.canonical_status == "CANCELLED"
    assert confirmation.requires_review is False  # expected confirmation, not an anomaly
    with env.sessions() as s:
        assert s.scalar(select(func.count()).select_from(ShippingWebhookEvent)) == 1


def test_replay_job_attaches_events_whose_shipment_appeared_later(env, client):
    from app.jobs.replay_webhooks import replay_pending
    from app.repositories.shipping import Actor, ActorType, NewShipment, ShippingRepository

    client.post(HOOK, content=vtp(200, "29/09/2026 10:00:00", number="LATE1"))
    assert env.webhooks()[0].processing_status == "IGNORED"
    assert replay_pending(env.sessions, env.applier) == 0  # still no shipment: untouched
    with env.sessions() as s, s.begin():
        repo = ShippingRepository(s)
        provider = repo.get_provider_by_code("VIETTEL_POST")
        sid = repo.create_shipment(
            NewShipment(
                order_id="ORD-LATE",
                provider_id=provider.id,
                tracking_number="LATE1",
                status="CREATED",
            ),
            Actor(ActorType.SYSTEM),
        ).id
    assert replay_pending(env.sessions, env.applier) == 1
    assert env.shipment(sid).status == "PICKED"
    assert replay_pending(env.sessions, env.applier) == 0  # idempotent
