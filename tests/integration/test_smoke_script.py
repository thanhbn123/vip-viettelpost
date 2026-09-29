"""The staging smoke test itself, run against the in-process app (G14)."""

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.api.auth import hash_key
from app.core.config import settings
from app.db.session import make_engine
from app.main import app
from scripts.smoke_test import run_checks

pytestmark = pytest.mark.real_auth
KEY = "smoke-test-key-not-real-0123456789abcdef"


def test_smoke_passes_on_a_correct_deployment(migrated_url, monkeypatch, make_env):
    make_env()  # application + webhook wired to the migrated database
    engine = make_engine(migrated_url)
    monkeypatch.setattr(health, "get_engine", lambda: engine)
    monkeypatch.setattr(settings, "api_keys", f"smoke:{hash_key(KEY)}")
    monkeypatch.setattr(settings, "webhook_shared_secret", "whk-test-not-real")
    monkeypatch.setattr(settings, "vtp_token", "eyJfake.not.real")
    from app.api.dependencies import get_operations
    from app.services.operations import ShipmentOperations
    from app.db.session import make_session_factory

    app.dependency_overrides[get_operations] = lambda: ShipmentOperations(
        make_session_factory(engine)
    )
    with TestClient(app) as client:
        results = run_checks(client, KEY)
    engine.dispose()
    failed = [(r.name, r.detail) for r in results if not r.ok]
    assert failed == []


def test_smoke_detects_a_misconfigured_deployment(monkeypatch, tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'empty.db'}")  # never the default URL
    monkeypatch.setattr(health, "get_engine", lambda: engine)
    monkeypatch.setattr(settings, "api_keys", None)  # auth not configured -> 503
    monkeypatch.setattr(settings, "webhook_shared_secret", None)
    with TestClient(app) as client:
        results = {r.name: r.ok for r in run_checks(client, KEY)}
    assert results["liveness /health"] is True
    assert results["API accepts key; VIETTEL_POST enabled"] is False
    assert results["webhook refuses wrong TOKEN (no side effect)"] is False  # 503, not 401
