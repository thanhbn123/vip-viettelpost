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
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: f"INFO clean {deployed.headers['X-Request-ID']}\n",
        vtp_evidence=None,
    )
    statuses = {c.name: c.status for c in ev.checks}
    assert statuses == dict.fromkeys(acceptance.G15_CHECKS, "PASS"), ev.checks
    assert (ev.g15, ev.verdict, ev.g08) == ("PASS", "ACCEPTED", "BLOCKED_EXTERNAL_CREDENTIAL")


def test_rehearsal_is_never_accepted(deployed):
    ev = acceptance.run(
        deployed,
        ENV,
        kind="rehearsal",
        expected_sha=SHA,
        logs=lambda: f"ok {deployed.headers['X-Request-ID']}\n",
        vtp_evidence=None,
    )
    assert ev.verdict == "REHEARSAL_PASS" and ev.g15 == "NOT_STAGING"


def test_missing_log_excerpt_blocks_acceptance(deployed):
    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha=SHA, logs=None, vtp_evidence=None
    )
    assert ev.verdict == "NOT_ACCEPTED" and ev.g15 == "FAIL"


def test_wrong_running_sha_fails(deployed):
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha="c" * 40,
        logs=lambda: f"ok {deployed.headers['X-Request-ID']}\n",
        vtp_evidence=None,
    )
    assert {c.name: c.status for c in ev.checks}["deployed_sha"] == "FAIL"
    assert ev.verdict == "NOT_ACCEPTED"


def test_secret_in_logs_is_detected_by_name_only(deployed):
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: f"{deployed.headers['X-Request-ID']} oops token={HOOK_SECRET}\n",
        vtp_evidence=None,
    )
    check = {c.name: c for c in ev.checks}["log_redaction"]
    assert check.status == "FAIL" and "ACCEPT_WEBHOOK_SECRET" in check.detail
    assert HOOK_SECRET not in json.dumps([c.__dict__ for c in ev.checks])


def test_g08_needs_real_dev_evidence(deployed):
    good = {
        "base_url": "https://partnerdev.viettelpost.vn",
        "sha": SHA,
        "auth_mode": "login",  # Login + ownerconnect: Viettel Post itself checked it
        "steps": [
            {"name": n, "status": "PASS"} for n in ("authenticate", "get_services", "calculate_fee")
        ],
    }
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: f"ok {deployed.headers['X-Request-ID']}\n",
        vtp_evidence=good,
    )
    assert ev.g08 == "PASS"
    mocked = {**good, "base_url": "https://vtp.test"}
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: f"ok {deployed.headers['X-Request-ID']}\n",
        vtp_evidence=mocked,
    )
    assert ev.g08 == "FAIL"


def _g08(deployed, evidence):
    return acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: f"ok {deployed.headers['X-Request-ID']}\n",
        vtp_evidence=evidence,
    ).g08


def test_g08_static_token_with_reads_only_is_not_verified(deployed):
    """CR-STG-007: a FAKE static token passed authenticate/services/fee on partnerdev (the
    read endpoints do not check it), so reads alone must not give G08 PASS."""
    reads = [
        {"name": n, "status": "PASS"} for n in ("authenticate", "get_services", "calculate_fee")
    ]
    base = {"base_url": "https://partnerdev.viettelpost.vn", "sha": SHA, "steps": reads}
    assert _g08(deployed, {**base, "auth_mode": "static_token"}) == "CREDENTIAL_NOT_VERIFIED"
    assert _g08(deployed, base) == "CREDENTIAL_NOT_VERIFIED"  # old evidence: no auth_mode
    created = reads + [
        {"name": "create_shipment", "status": "PASS"},
        {"name": "cancel_shipment", "status": "PASS"},
    ]
    assert _g08(deployed, {**base, "auth_mode": "static_token", "steps": created}) == "PASS"
    half = reads + [
        {"name": "create_shipment", "status": "PASS"},
        {"name": "cancel_shipment", "status": "FAIL"},
    ]
    assert _g08(deployed, {**base, "auth_mode": "static_token", "steps": half}) == "FAIL"
    login_failed = [{"name": "authenticate", "status": "FAIL"}]
    assert _g08(deployed, {**base, "auth_mode": "login", "steps": login_failed}) == "FAIL"


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
        return f"clean {deployed.headers['X-Request-ID']}\n"

    ev = acceptance.run(
        deployed, ENV, kind="staging", expected_sha=SHA, logs=provider, vtp_evidence=None
    )
    assert calls == [0] and ev.verdict == "ACCEPTED"


# --- verifier findings on PR #28 --------------------------------------------------------


def test_empty_or_foreign_logs_are_not_run(deployed):
    for logs in ("", "   \n", "INFO lines from some other instance\n"):
        ev = acceptance.run(
            deployed, ENV, kind="staging", expected_sha=SHA, logs=logs, vtp_evidence=None
        )
        assert {c.name: c.status for c in ev.checks}["log_redaction"] == "NOT_RUN"
        assert ev.verdict == "NOT_ACCEPTED"


def test_smoke_responses_are_scanned_too(deployed):
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: deployed.headers["X-Request-ID"],
        vtp_evidence=None,
    )
    detail = {c.name: c.detail for c in ev.checks}["no_secret_in_responses"]
    assert int(detail.split()[0]) >= 15  # 4 health/ready + 9+ smoke + 4 webhook


def test_vtp_evidence_must_belong_to_this_sha(deployed):
    base = {
        "base_url": "https://partnerdev.viettelpost.vn",
        "steps": [
            {"name": n, "status": "PASS"} for n in ("authenticate", "get_services", "calculate_fee")
        ],
    }
    for forged in (base, {**base, "sha": "d" * 40}, {"steps": "nonsense"}, {"malformed": True}):
        ev = acceptance.run(
            deployed,
            ENV,
            kind="staging",
            expected_sha=SHA,
            logs=lambda: deployed.headers["X-Request-ID"],
            vtp_evidence=forged,
        )
        assert ev.g08 == "FAIL"


def test_rehearsal_never_reports_g08(deployed):
    good = {
        "base_url": "https://partnerdev.viettelpost.vn",
        "sha": SHA,
        "steps": [
            {"name": n, "status": "PASS"} for n in ("authenticate", "get_services", "calculate_fee")
        ],
    }
    ev = acceptance.run(
        deployed,
        ENV,
        kind="rehearsal",
        expected_sha=SHA,
        logs=lambda: deployed.headers["X-Request-ID"],
        vtp_evidence=good,
    )
    assert ev.g08 == "NOT_STAGING"


def test_url_password_is_found_decoded_too():
    env = {"ACCEPT_SCAN_VARS": "DB", "DB": "postgresql://u:" + "p%40ssword99" + "@h/db"}
    secrets = acceptance.secret_values(env)
    assert acceptance.leaked("log p@ssword99", secrets) == ["DB"]


def test_userinfo_in_staging_url_is_refused(tmp_path):
    assert (
        acceptance.main(
            [
                "--base-url",
                "https://u:" + "p@x",
                "--kind",
                "staging",
                "--expected-sha",
                SHA,
                "--evidence",
                str(tmp_path / "e"),
            ],
            env={},
        )
        == 2
    )


def test_real_e2e_script_evidence_is_accepted_for_g08(deployed, tmp_path):
    """End to end (verifier H1 on PR #28): the evidence file the E2E script really writes,
    with VTP_E2E_SHA set exactly as staging.yml sets it, must give G08 PASS - not a
    hand-written fixture."""
    import httpx

    from scripts import vtp_dev_e2e
    from tests.unit.test_vtp_dev_e2e_script import ROUTES, SCENARIO
    from tests.unit.vtp_fakes import Recorder

    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(SCENARIO))
    evidence = tmp_path / "vtp-evidence.json"
    env = {
        "VTP_BASE_URL": "https://partnerdev.viettelpost.vn",
        "VTP_TOKEN": "eyJfake.e2e.x",
        "VTP_E2E_SCENARIO": str(scenario),
        "VTP_E2E_SHA": SHA,
    }
    code = vtp_dev_e2e.main(
        ["--evidence", str(evidence)], env=env, transport=httpx.MockTransport(Recorder(ROUTES))
    )
    assert code == 0
    real = json.loads(evidence.read_text())
    assert real["sha"] == SHA and real["auth_mode"] == "static_token"
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: deployed.headers["X-Request-ID"],
        vtp_evidence=real,
    )
    assert ev.g08 == "CREDENTIAL_NOT_VERIFIED"  # CR-STG-007: reads do not prove the token
    code = vtp_dev_e2e.main(
        ["--create", "--evidence", str(evidence)],
        env={**env, "VTP_E2E_ALLOW_CREATE": "yes"},
        transport=httpx.MockTransport(Recorder(ROUTES)),
    )
    assert code == 0
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: deployed.headers["X-Request-ID"],
        vtp_evidence=json.loads(evidence.read_text()),
    )
    assert ev.g08 == "PASS"

    env.pop("VTP_E2E_SHA")
    vtp_dev_e2e.main(
        ["--evidence", str(evidence)], env=env, transport=httpx.MockTransport(Recorder(ROUTES))
    )
    ev = acceptance.run(
        deployed,
        ENV,
        kind="staging",
        expected_sha=SHA,
        logs=lambda: deployed.headers["X-Request-ID"],
        vtp_evidence=json.loads(evidence.read_text()),
    )
    assert ev.g08 == "FAIL"  # evidence not bound to this SHA


def test_login_mode_script_evidence_gives_g08_pass(deployed, tmp_path):
    """CR-STG-007: a username/password run (Login + ownerconnect over the network) records
    auth_mode=login and is accepted without create; a rejected login is FAIL."""
    import httpx

    from app.providers.viettel_post.auth import LOGIN_PATH, OWNER_CONNECT_PATH
    from scripts import vtp_dev_e2e
    from tests.unit.test_vtp_auth import login_ok, owner_ok
    from tests.unit.test_vtp_dev_e2e_script import ROUTES, SCENARIO
    from tests.unit.vtp_fakes import Recorder, rejected, respond

    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(SCENARIO))
    evidence = tmp_path / "vtp-evidence.json"
    env = {
        "VTP_BASE_URL": "https://partnerdev.viettelpost.vn",
        "VTP_USERNAME": "fake-test-user",
        "VTP_PASSWORD": "fake-test-pass",
        "VTP_E2E_SCENARIO": str(scenario),
        "VTP_E2E_SHA": SHA,
    }
    routes = {**ROUTES, LOGIN_PATH: login_ok(), OWNER_CONNECT_PATH: owner_ok()}
    recorder = Recorder(routes)
    assert (
        vtp_dev_e2e.main(
            ["--evidence", str(evidence)], env=env, transport=httpx.MockTransport(recorder)
        )
        == 0
    )
    real = json.loads(evidence.read_text())
    assert real["auth_mode"] == "login"
    assert [r.url.path for r in recorder.requests][:2] == [LOGIN_PATH, OWNER_CONNECT_PATH]
    assert _g08(deployed, real) == "PASS"

    bad = {**routes, LOGIN_PATH: respond(rejected("Invalid owner account or password!"))}
    vtp_dev_e2e.main(
        ["--evidence", str(evidence)], env=env, transport=httpx.MockTransport(Recorder(bad))
    )
    assert _g08(deployed, json.loads(evidence.read_text())) == "FAIL"
