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
    from app.api.auth import hash_key

    monkeypatch.setattr(settings, "api_keys", f"ready:{hash_key('ready-test-key-not-real-000000')}")
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
    import app.api.health as health

    health._backlog_cache = None
    with TestClient(app) as client:
        body = client.get("/metrics").json()
    assert set(body) == {"counters", "timings", "gauges"}
    backlog = next(
        g for g in body["gauges"] if g["name"] == "webhook_events_unmatched_with_shipment"
    )
    assert "value" in backlog or "error" in backlog


def test_replay_backlog_gauge_degrades_instead_of_breaking_metrics():
    """The gauge is what makes a replay job nobody scheduled visible at all."""
    import app.api.health as health

    class Broken:
        def __call__(self):
            raise RuntimeError("no database here")

    health._backlog_cache = None
    assert health.replay_backlog(Broken()) == {
        "name": "webhook_events_unmatched_with_shipment",
        "error": "RuntimeError",
    }
    health._backlog_cache = None


def test_replay_backlog_gauge_is_cached_so_scrape_rate_does_not_drive_db_load():
    import app.api.health as health

    calls = []

    class Counting:
        def __call__(self):
            calls.append(1)
            raise RuntimeError("counted")

    health._backlog_cache = None
    clock = [1000.0]
    health.replay_backlog(Counting(), now=lambda: clock[0])
    health.replay_backlog(Counting(), now=lambda: clock[0] + 30)
    assert len(calls) == 1, "a second scrape inside the TTL must not hit the database"
    clock[0] += health._BACKLOG_TTL_SECONDS + 1
    health.replay_backlog(Counting(), now=lambda: clock[0])
    assert len(calls) == 2, "the gauge must refresh once the TTL has passed"
    health._backlog_cache = None


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


def test_not_ready_without_api_keys(migrated_url, monkeypatch):
    engine = make_engine(migrated_url)
    monkeypatch.setattr(health, "get_engine", lambda: engine)
    monkeypatch.setattr(settings, "api_keys", None)
    checks = health.readiness_checks()
    engine.dispose()
    assert checks["api_keys"]["ok"] is False


def test_readiness_reports_the_running_commit(monkeypatch):
    monkeypatch.setattr(settings, "app_git_sha", "a" * 40)
    monkeypatch.setattr(health, "get_engine", lambda: make_engine("sqlite://"))
    with TestClient(app) as client:
        body = client.get("/health/ready").json()
    assert body["version"] == "a" * 40


def test_replay_backlog_gauge_counts_only_events_whose_shipment_now_exists(migrated_url):
    """What the gauge means, on real rows, on both backends.

    Counted: an event the replay job could attach today, because the shipment it refers
    to has since been recorded. Not counted: an event whose shipment still does not
    exist (nothing to attach it to) and one already processed.
    """
    from sqlalchemy import text

    from app.db.session import make_session_factory

    engine = make_engine(migrated_url)
    sessions = make_session_factory(engine)
    with sessions() as session:
        provider = session.execute(text("select id from shipping_providers limit 1")).scalar()

        def event(tracking, status, error=None):
            session.execute(
                text(
                    "insert into shipping_webhook_events (provider_id, fingerprint,"
                    " tracking_number, payload_json, received_at, processing_status,"
                    " attempt_count, error_code) values (:p, :f, :t, '{}', CURRENT_TIMESTAMP,"
                    " :s, 0, :e)"
                ),
                {
                    "p": provider,
                    "f": f"{tracking}{status}"[:20].ljust(64, "0"),
                    "t": tracking,
                    "s": status,
                    "e": error,
                },
            )

        event("TRK-HAS-SHIPMENT", "IGNORED", "SHIPMENT_NOT_FOUND")  # counted
        event("TRK-HAS-SHIPMENT", "FAILED")  # counted
        event("TRK-NO-SHIPMENT", "IGNORED", "SHIPMENT_NOT_FOUND")  # no shipment to attach
        event("TRK-HAS-SHIPMENT", "PROCESSED")  # already done
        session.execute(
            text(
                "insert into shipments (provider_id, order_id, tracking_number, status,"
                " created_at, updated_at) values (:p, 'ORD-1', 'TRK-HAS-SHIPMENT',"
                " 'READY_TO_PICK', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"p": provider},
        )
        session.commit()

    health._backlog_cache = None
    try:
        assert health.replay_backlog(sessions) == {
            "name": "webhook_events_unmatched_with_shipment",
            "value": 2,
        }
    finally:
        health._backlog_cache = None
        engine.dispose()
