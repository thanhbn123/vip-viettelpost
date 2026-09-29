"""G12: API key authentication, body size limit, security headers (real dependency)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.auth import hash_key, parse_api_keys
from app.core.config import settings
from app.db.models import ShippingAuditLog
from app.main import app
from tests.integration.test_shipping_api import BASE, create_body

pytestmark = pytest.mark.real_auth

KEY = "test-api-key-0123456789-abcdefghijkl"  # test value only
OTHER = "another-test-key-9876543210-zyxwvut"


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "api_keys", f"ops:{hash_key(KEY)},svc:{hash_key(OTHER)}")


def test_parse_api_keys():
    assert parse_api_keys(None) == ()
    assert parse_api_keys(f"a:{'0' * 64}, b:{'1' * 64}") == (("a", "0" * 64), ("b", "1" * 64))
    for bad in (f"a:{'0' * 63}", "a:not-hex", f"a b:{'0' * 64}", f"a:{'0' * 64},a:{'1' * 64}"):
        with pytest.raises(ValueError):
            parse_api_keys(bad)


def test_fail_closed_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "api_keys", None)
    with TestClient(app) as client:
        response = client.get(f"{BASE}/providers", headers={"X-API-Key": KEY})
    assert response.status_code == 503 and response.json()["error"] == "auth_not_configured"


@pytest.mark.parametrize(
    "headers", [{}, {"X-API-Key": ""}, {"X-API-Key": "wrong"}, {"Authorization": f"Bearer {KEY}"}]
)
def test_rejects_missing_or_wrong_key(keyed, headers):
    with TestClient(app) as client:
        for method, path in (
            ("get", "/providers"),
            ("get", "/shipments"),
            ("get", "/shipments/1/finance"),
            ("post", "/quote"),
        ):
            response = getattr(client, method)(f"{BASE}{path}", headers=headers)
            assert response.status_code == 401, (path, response.text)
            assert response.json()["error"] == "unauthorized"
        assert client.get("/metrics", headers=headers).status_code == 401


def test_public_endpoints_stay_open(keyed):
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health/ready").status_code in (200, 503)  # never 401
        webhook = client.post(f"{BASE}/webhooks/viettel-post", content=b"{}")
        # The webhook has its own TOKEN auth; the API-key layer never answers for it.
        assert webhook.json().get("error") != "unauthorized"


def test_valid_key_is_accepted_and_becomes_the_audit_actor(keyed, make_env):
    env = make_env()
    with TestClient(app) as client:
        assert client.get(f"{BASE}/providers", headers={"X-API-Key": KEY}).status_code == 200
        created = client.post(f"{BASE}/shipments", json=create_body(), headers={"X-API-Key": OTHER})
        assert created.status_code == 201
        assert client.get("/metrics", headers={"X-API-Key": KEY}).status_code == 200
    with env.sessions() as s:
        actors = {row.actor_id for row in s.scalars(select(ShippingAuditLog))}
    assert actors == {"apikey:svc"}
    assert all(KEY not in (a or "") and OTHER not in (a or "") for a in actors)


def test_security_headers_and_body_limit(keyed, monkeypatch):
    monkeypatch.setattr(settings, "api_max_body_bytes", 100)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"
        big = client.post(
            f"{BASE}/quote",
            content=b"x" * 500,
            headers={"X-API-Key": KEY, "Content-Type": "application/json"},
        )
        assert big.status_code == 413 and big.json()["error"] == "payload_too_large"


def test_generate_key_tool(capsys):
    from app.tools.api_key import main

    assert main(["ops"]) == 0
    out = capsys.readouterr().out.splitlines()
    raw = out[0].split(": ", 1)[1]
    entry = out[1].split(": ", 1)[1]
    assert entry == f"ops:{hash_key(raw)}" and len(raw) >= 32


def test_database_errors_never_carry_sql_parameters(migrated_url):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.db.session import make_engine

    engine = make_engine(migrated_url)
    with pytest.raises(IntegrityError) as info:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO shipping_providers (code, name, enabled, created_at, updated_at) "
                    "VALUES (:c, :n, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"c": "VIETTEL_POST", "n": "Nguyễn Văn Riêng Tư 0901234567"},
            )
    engine.dispose()
    assert "0901234567" not in str(info.value)
