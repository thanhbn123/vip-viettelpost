"""Acceptance runner against the real app in-process (CR-STG-001). Never counts as staging."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.api.auth import hash_key
from app.core.config import settings
from app.db.session import make_engine
from app.main import app
from scripts.staging import acceptance

pytestmark = pytest.mark.real_auth
SHA = "b" * 40
KEY = "acceptance-test-key-not-real-000000"
HOOK_SECRET = "whk-acceptance-test-not-real"


@pytest.fixture
def deployed(make_env, migrated_url, monkeypatch):
    make_env()
    engine = make_engine(migrated_url)
    monkeypatch.setattr(health, "get_engine", lambda: engine)
    monkeypatch.setattr(settings, "api_keys", f"accept:{hash_key(KEY)}")
    monkeypatch.setattr(settings, "webhook_shared_secret", HOOK_SECRET)
    monkeypatch.setattr(settings, "vtp_token", "eyJfake.not.real")
    monkeypatch.setattr(settings, "app_git_sha", SHA)
    from app.api.dependencies import get_operations
    from app.db.session import make_session_factory
    from app.services.operations import ShipmentOperations
    from app.webhooks.dependencies import get_vtp_webhook_processor
    from app.webhooks.processor import WebhookProcessor
    from app.webhooks.sql_sink import SqlWebhookSink

    sessions = make_session_factory(engine)
    app.dependency_overrides[get_operations] = lambda: ShipmentOperations(sessions)
    app.dependency_overrides[get_vtp_webhook_processor] = lambda: WebhookProcessor(
        shared_secret=HOOK_SECRET, sink=SqlWebhookSink(sessions)
    )
    with TestClient(app) as client:
        yield client
    engine.dispose()


ENV = {
    "ACCEPT_API_KEY": KEY,
    "ACCEPT_WEBHOOK_SECRET": HOOK_SECRET,
    "ACCEPT_SCAN_VARS": "ACCEPT_API_KEY,ACCEPT_WEBHOOK_SECRET",
}


def test_all_checks_pass_on_a_correct_deployment(deployed):
    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha=SHA, logs="INFO clean line\n", vtp_evidence=None
    )
    statuses = {c.name: c.status for c in ev.checks}
    assert statuses == dict.fromkeys(acceptance.G15_CHECKS, "PASS"), ev.checks
    assert (ev.g15, ev.verdict, ev.g08) == ("PASS", "ACCEPTED", "BLOCKED_EXTERNAL_CREDENTIAL")


def test_rehearsal_is_never_accepted(deployed):
    ev = acceptance.run(
        deployed, ENV, kind="rehearsal", expected_sha=SHA, logs="ok\n", vtp_evidence=None
    )
    assert ev.verdict == "REHEARSAL_PASS" and ev.g15 == "NOT_STAGING"


def test_missing_log_excerpt_blocks_acceptance(deployed):
    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha=SHA, logs=None, vtp_evidence=None
    )
    assert ev.verdict == "NOT_ACCEPTED" and ev.g15 == "FAIL"


def test_wrong_running_sha_fails(deployed):
    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha="c" * 40, logs="ok\n", vtp_evidence=None
    )
    assert {c.name: c.status for c in ev.checks}["deployed_sha"] == "FAIL"
    assert ev.verdict == "NOT_ACCEPTED"


def test_secret_in_logs_is_detected_by_name_only(deployed):
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=f"oops token={HOOK_SECRET}\n",
        vtp_evidence=None,
    )
    check = {c.name: c for c in ev.checks}["log_redaction"]
    assert check.status == "FAIL" and "ACCEPT_WEBHOOK_SECRET" in check.detail
    assert HOOK_SECRET not in json.dumps([c.__dict__ for c in ev.checks])


def test_g08_needs_real_dev_evidence(deployed):
    good = {
        "base_url": "https://partnerdev.viettelpost.vn",
        "steps": [
            {"name": n, "status": "PASS"} for n in ("authenticate", "get_services", "calculate_fee")
        ],
    }
    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha=SHA, logs="ok\n", vtp_evidence=good
    )
    assert ev.g08 == "PASS"
    mocked = {**good, "base_url": "https://vtp.test"}
    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha=SHA, logs="ok\n", vtp_evidence=mocked
    )
    assert ev.g08 == "FAIL"


def test_cli_refuses_http_for_staging_and_bad_sha(tmp_path):
    ev = str(tmp_path / "e.json")
    assert (
        acceptance.main(
            [
                "--base-url",
                "http://x",
                "--kind",
                "staging",
                "--expected-sha",
                SHA,
                "--evidence",
                ev,
            ],
            env={},
        )
        == 2
    )
    assert (
        acceptance.main(
            [
                "--base-url",
                "https://x",
                "--kind",
                "staging",
                "--expected-sha",
                "abc",
                "--evidence",
                ev,
            ],
            env={},
        )
        == 2
    )


def test_log_provider_is_called_after_the_http_checks(deployed):
    calls = []

    def provider():
        calls.append(len(calls))
        return "clean\n"

    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha=SHA, logs=provider, vtp_evidence=None
    )
    assert calls == [0] and ev.verdict == "ACCEPTED"
