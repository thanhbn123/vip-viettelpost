"""CR-READY-001: the REAL webhook dependency (app/webhooks/dependencies.py) - secret from
settings, durable SQL sink on the configured database, shipment applier - updates an existing
shipment. Every other webhook test overrides this dependency, so dropping ``after_store``
there would not have been caught."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.dependencies import get_application
from app.core import database
from app.core.config import settings
from app.db.models import ShippingAuditLog
from app.main import app
from app.webhooks import dependencies as hook_deps
from tests.integration.test_webhook_to_shipment import BASE, HOOK, SECRET, Env, created, vtp


def _clear_caches():
    for fn in (
        database.get_engine,
        database.get_session_factory,
        hook_deps.get_vtp_webhook_processor,
        hook_deps.get_webhook_applier,
    ):
        fn.cache_clear()


@pytest.fixture
def real_wiring(migrated_url, monkeypatch):
    monkeypatch.setattr(settings, "database_url", migrated_url)
    monkeypatch.setattr(settings, "webhook_shared_secret", SECRET)
    monkeypatch.setattr(settings, "vtp_webhook_timezone", None)
    _clear_caches()
    env = Env(migrated_url)
    app.dependency_overrides[get_application] = lambda: env.app
    assert get_application in app.dependency_overrides
    assert hook_deps.get_vtp_webhook_processor not in app.dependency_overrides
    try:
        with TestClient(app) as client:
            yield env, client
    finally:
        app.dependency_overrides.clear()
        if database.get_engine.cache_info().currsize:
            database.get_engine().dispose()
        _clear_caches()
        env.engine.dispose()


def test_real_dependency_applies_103_then_107_to_an_existing_shipment(real_wiring):
    env, client = real_wiring
    sid = created(client)
    r = client.post(HOOK, content=vtp(103, "02/10/2026 14:37:32"))
    assert r.status_code == 200 and r.json()["result"] == "ACCEPTED"
    assert env.shipment(sid).status == "READY_TO_PICK"
    r = client.post(HOOK, content=vtp(107, "02/10/2026 14:37:40"))
    assert r.status_code == 200
    shipment = env.shipment(sid)
    assert (shipment.status, shipment.provider_status) == ("CANCELLED", "107")
    hooks = env.webhooks()
    assert [h.processing_status for h in hooks] == ["PROCESSED", "PROCESSED"]
    assert all(h.shipment_id == sid for h in hooks)
    assert len(env.events(sid)) == 2
    with env.sessions() as s:
        actions = [a.action for a in s.scalars(select(ShippingAuditLog))]
    assert actions.count("STATUS_CHANGED_BY_PROVIDER") == 2
    assert client.get(f"{BASE}/shipments/{sid}").json()["status"] == "CANCELLED"


def test_real_dependency_rejects_a_wrong_secret(real_wiring):
    env, client = real_wiring
    sid = created(client)
    r = client.post(HOOK, content=vtp(103, "02/10/2026 14:37:32", token="wrong-not-real"))
    assert r.status_code == 401
    assert env.shipment(sid).status == "CREATED" and env.webhooks() == []
