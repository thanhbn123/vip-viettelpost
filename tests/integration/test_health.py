"""G11 readiness: database, migration head, configuration presence (never values)."""

from fastapi.testclient import TestClient

from app.api import health
from app.core.config import settings
from app.db.session import make_engine
from app.main import app


def test_liveness():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_ready_when_migrated_and_configured(migrated_url, monkeypatch):
    engine = make_engine(migrated_url)
    monkeypatch.setattr(health, "get_engine", lambda: engine)
    monkeypatch.setattr(settings, "webhook_shared_secret", "whk-test-not-real")
    monkeypatch.setattr(settings, "vtp_token", "eyJfake.not.real")
    with TestClient(app) as client:
        response = client.get("/health/ready")
    engine.dispose()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["migrations"]["current"] == health.expected_head()
    assert "whk-test-not-real" not in response.text and "eyJfake" not in response.text


def test_not_ready_without_schema_or_config(db_url, monkeypatch):
    engine = make_engine(db_url)  # empty database, no migrations
    monkeypatch.setattr(health, "get_engine", lambda: engine)
    monkeypatch.setattr(settings, "webhook_shared_secret", None)
    with TestClient(app) as client:
        response = client.get("/health/ready")
    engine.dispose()
    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["database"]["ok"] is True  # reachable
    assert checks["migrations"]["ok"] is False  # but not migrated
    assert checks["webhook_secret"]["ok"] is False


def test_not_ready_when_database_unreachable(monkeypatch):
    engine = make_engine(
        "postgresql+psycopg://nobody@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr(health, "get_engine", lambda: engine)
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == {"ok": False, "error": "OperationalError"}


def test_metrics_endpoint():
    with TestClient(app) as client:
        body = client.get("/metrics").json()
    assert set(body) == {"counters", "timings"}


def test_unexpected_error_log_line_carries_the_request_id():
    import logging

    from app.api.dependencies import get_application
    from app.core.logging import RequestIdFilter

    class Broken:
        def get_shipment(self, shipment_id):
            raise RuntimeError("boom")

    seen = []

    class Capture(logging.Handler):
        def emit(self, record):
            seen.append(getattr(record, "request_id", None))

    handler = Capture()
    handler.addFilter(RequestIdFilter())  # evaluated at emit time, like production
    logger = logging.getLogger("app.api.errors")
    logger.addHandler(handler)
    app.dependency_overrides[get_application] = lambda: Broken()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.get("/api/v1/shipping/shipments/1", headers={"X-Request-ID": "rid-log"})
    finally:
        logger.removeHandler(handler)
        app.dependency_overrides.pop(get_application, None)
    assert "rid-log" in seen


def test_broken_migration_tree_is_not_ready_not_500(monkeypatch):
    def broken():
        raise RuntimeError("multiple heads")

    monkeypatch.setattr(health, "expected_head", broken)
    checks = health.readiness_checks(engine=make_engine("sqlite://"))
    assert checks["migration_scripts"]["ok"] is False
