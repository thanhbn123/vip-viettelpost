"""scripts/vtp_dev_e2e.py guards and sequence (mock HTTP only; never reaches Viettel Post)."""

import json

import httpx
import pytest

from app.core.config import VTP_DEV_BASE_URL, VTP_PRODUCTION_BASE_URL
from app.providers.viettel_post import mapping
from scripts import vtp_dev_e2e as e2e
from tests.unit.test_vtp_api import CANCEL_SAMPLE, CREATE_SAMPLE, FEE_SAMPLE, SERVICES_SAMPLE
from tests.unit.vtp_fakes import Recorder, respond

TOKEN = "eyJfake.e2e.not-real-token"
SCENARIO = {
    "sender": {"name": "S", "phone": "0900000000", "address_line": "a", "province": "p"},
    "receiver": {"name": "R", "phone": "0900000001", "address_line": "b", "province": "q"},
    "packages": [{"weight_grams": 500}],
    "service_code": None,
    "provider_options": {
        "sender_location": {"province_id": 1, "district_id": None, "ward_id": 2},
        "receiver_location": {"province_id": 3, "district_id": None, "ward_id": 4},
        "order_payment": 1,
    },
}
ROUTES = {
    mapping.GET_SERVICES_PATH: respond(SERVICES_SAMPLE),
    mapping.CALCULATE_FEE_PATH: respond(FEE_SAMPLE),
    mapping.CREATE_ORDER_PATH: respond(CREATE_SAMPLE),
    mapping.UPDATE_ORDER_STATUS_PATH: respond(CANCEL_SAMPLE),
}


def env(tmp_path, **extra):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(SCENARIO))
    return {
        "VTP_BASE_URL": VTP_DEV_BASE_URL,
        "VTP_TOKEN": TOKEN,
        "VTP_E2E_SCENARIO": str(path),
        **extra,
    }


def run(tmp_path, argv, environ, recorder=None):
    evidence = tmp_path / "evidence.json"
    transport = httpx.MockTransport(recorder) if recorder else None
    code = e2e.main([*argv, "--evidence", str(evidence)], env=environ, transport=transport)
    return code, (json.loads(evidence.read_text()) if evidence.exists() else None)


def test_refuses_production_url_without_any_request(tmp_path, capsys):
    recorder = Recorder(ROUTES)
    code, _ = run(tmp_path, [], env(tmp_path, VTP_BASE_URL=VTP_PRODUCTION_BASE_URL), recorder)
    assert code == e2e.EXIT_REFUSED and recorder.requests == []
    assert "REFUSED" in capsys.readouterr().out


def test_blocked_without_credentials(tmp_path, capsys):
    environ = env(tmp_path)
    environ.pop("VTP_TOKEN")
    code, _ = run(tmp_path, [], environ)
    assert code == e2e.EXIT_BLOCKED
    assert "BLOCKED_EXTERNAL_CREDENTIAL" in capsys.readouterr().out


def test_read_only_by_default(tmp_path, capsys):
    recorder = Recorder(ROUTES)
    code, evidence = run(tmp_path, [], env(tmp_path), recorder)
    assert code == e2e.EXIT_OK
    status = {s["name"]: s["status"] for s in evidence["steps"]}
    assert status == {
        "authenticate": "PASS",
        "get_services": "PASS",
        "calculate_fee": "PASS",
        "create_shipment": "NOT_SAFE",
        "cancel_shipment": "SKIPPED",
    }
    paths = {r.url.path for r in recorder.requests}
    assert mapping.CREATE_ORDER_PATH not in paths and mapping.UPDATE_ORDER_STATUS_PATH not in paths
    out = capsys.readouterr().out + json.dumps(evidence)
    assert TOKEN not in out and "0900000000" not in out


def test_create_needs_flag_and_allow(tmp_path):
    recorder = Recorder(ROUTES)
    code, evidence = run(tmp_path, ["--create"], env(tmp_path), recorder)  # no ALLOW
    assert code == e2e.EXIT_OK
    assert {s["name"]: s["status"] for s in evidence["steps"]}["create_shipment"] == "NOT_SAFE"
    assert mapping.CREATE_ORDER_PATH not in {r.url.path for r in recorder.requests}


def test_create_then_cancel_when_authorised(tmp_path):
    recorder = Recorder(ROUTES)
    code, evidence = run(
        tmp_path, ["--create"], env(tmp_path, VTP_E2E_ALLOW_CREATE="yes"), recorder
    )
    assert code == e2e.EXIT_OK
    steps = {s["name"]: s for s in evidence["steps"]}
    assert steps["create_shipment"]["evidence"]["tracking_number"] == "15878180012"
    assert steps["cancel_shipment"]["evidence"] == {
        "tracking_number": "15878180012",
        "cancelled": True,
        "attempts": 1,
    }
    assert [r.url.path for r in recorder.requests][-1] == mapping.UPDATE_ORDER_STATUS_PATH
    # CR-STG-008: the cancel carries a NOTE (the owner's successful manual cancel had one)
    (cancel_body,) = recorder.bodies(mapping.UPDATE_ORDER_STATUS_PATH)
    assert cancel_body["TYPE"] == 4 and cancel_body["NOTE"]


def test_failed_step_is_reported_not_raised(tmp_path):
    routes = {**ROUTES, mapping.CALCULATE_FEE_PATH: respond({"message": "down"}, 503)}
    code, evidence = run(tmp_path, [], env(tmp_path), Recorder(routes))
    assert code == e2e.EXIT_FAIL
    fee = {s["name"]: s for s in evidence["steps"]}["calculate_fee"]
    assert fee["status"] == "FAIL" and fee["error"].startswith("ViettelPostServerError")


def test_bad_scenario_is_refused(tmp_path):
    code, _ = run(tmp_path, [], {**env(tmp_path), "VTP_E2E_SCENARIO": str(tmp_path / "nope")})
    assert code == e2e.EXIT_REFUSED


# --- verifier findings on PR #25 --------------------------------------------------------


def _exact_command(args, extra_env):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    clean = {k: v for k, v in os.environ.items() if not k.startswith("VTP_")}
    return subprocess.run(
        [sys.executable, *args],
        cwd=root,
        env={**clean, **extra_env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_workflow_command_runs_and_is_blocked_without_credentials():
    """The exact command used by staging.yml (module form) must import and exit 3."""
    result = _exact_command(["-m", "scripts.vtp_dev_e2e"], {})
    assert result.returncode == e2e.EXIT_BLOCKED, result.stderr
    assert "BLOCKED_EXTERNAL_CREDENTIAL" in result.stdout


def test_workflow_command_refuses_production():
    result = _exact_command(
        ["-m", "scripts.vtp_dev_e2e"], {"VTP_BASE_URL": VTP_PRODUCTION_BASE_URL, "VTP_TOKEN": TOKEN}
    )
    assert result.returncode == e2e.EXIT_REFUSED, result.stderr


def test_smoke_script_command_runs():
    result = _exact_command(["scripts/smoke_test.py"], {})
    assert result.returncode == 2 and "SMOKE_BASE_URL" in result.stderr


def test_empty_services_is_a_failure_and_blocks_create(tmp_path):
    routes = {**ROUTES, mapping.GET_SERVICES_PATH: respond([])}
    recorder = Recorder(routes)
    code, evidence = run(
        tmp_path, ["--create"], env(tmp_path, VTP_E2E_ALLOW_CREATE="yes"), recorder
    )
    assert code == e2e.EXIT_FAIL
    status = {s["name"]: s["status"] for s in evidence["steps"]}
    assert status["get_services"] == "FAIL" and status["create_shipment"] == "SKIPPED"
    assert mapping.CREATE_ORDER_PATH not in {r.url.path for r in recorder.requests}


def test_create_evidence_has_no_personal_data(tmp_path, capsys):
    code, evidence = run(
        tmp_path, ["--create"], env(tmp_path, VTP_E2E_ALLOW_CREATE="yes"), Recorder(ROUTES)
    )
    assert code == e2e.EXIT_OK
    text = json.dumps(evidence, ensure_ascii=False) + capsys.readouterr().out
    for value in ("0900000000", "0900000001", '"S"', '"R"', TOKEN):
        assert value not in text


def test_invalid_scenario_fields_are_refused_without_values(tmp_path, capsys):
    path = tmp_path / "bad.json"
    bad = {**SCENARIO, "sender": {**SCENARIO["sender"], "phone": ""}}
    path.write_text(json.dumps(bad))
    code, _ = run(tmp_path, [], {**env(tmp_path), "VTP_E2E_SCENARIO": str(path)})
    out = capsys.readouterr().out
    assert code == e2e.EXIT_REFUSED
    assert "invalid fields" in out and "phone" in out and "Traceback" not in out


def _sequence(*responders):
    calls = iter(responders)
    return lambda request: next(calls)(request)


def test_cancel_retries_a_business_refusal_then_succeeds(tmp_path):
    """CR-STG-008: run 36976623849 had cancel refused right after create; it is retried."""
    from tests.unit.vtp_fakes import rejected

    routes = {
        **ROUTES,
        mapping.UPDATE_ORDER_STATUS_PATH: _sequence(
            respond(rejected("Don hang chua san sang")), respond(CANCEL_SAMPLE)
        ),
    }
    recorder = Recorder(routes)
    environ = env(tmp_path, VTP_E2E_ALLOW_CREATE="yes", VTP_E2E_CANCEL_WAIT_SECONDS="0")
    code, evidence = run(tmp_path, ["--create"], environ, recorder)
    assert code == e2e.EXIT_OK
    cancel = {s["name"]: s for s in evidence["steps"]}["cancel_shipment"]
    assert cancel["status"] == "PASS" and cancel["evidence"]["attempts"] == 2


def test_cancel_failure_records_the_provider_message_without_secrets(tmp_path):
    from tests.unit.vtp_fakes import rejected

    secret = "fake-test-secret-pass-123"
    routes = {
        **ROUTES,
        mapping.UPDATE_ORDER_STATUS_PATH: respond(rejected(f"Khong huy duoc {secret}")),
    }
    environ = env(
        tmp_path,
        VTP_E2E_ALLOW_CREATE="yes",
        VTP_E2E_CANCEL_WAIT_SECONDS="0",
        VTP_E2E_CANCEL_RETRIES="2",
        VTP_PASSWORD=secret,
    )
    recorder = Recorder(routes)
    code, evidence = run(tmp_path, ["--create"], environ, recorder)
    assert code == e2e.EXIT_FAIL
    cancel = {s["name"]: s for s in evidence["steps"]}["cancel_shipment"]
    assert cancel["status"] == "FAIL"
    assert cancel["error"].startswith("ViettelPostBusinessError")
    assert "Khong huy duoc" in cancel["error"]
    assert secret not in json.dumps(evidence)
    paths = [r.url.path for r in recorder.requests]
    assert paths.count(mapping.UPDATE_ORDER_STATUS_PATH) == 2


def test_cancel_auth_error_is_not_retried(tmp_path):
    from tests.unit.vtp_fakes import rejected

    routes = {**ROUTES, mapping.UPDATE_ORDER_STATUS_PATH: respond(rejected("Token invalid"))}
    environ = env(tmp_path, VTP_E2E_ALLOW_CREATE="yes", VTP_E2E_CANCEL_WAIT_SECONDS="0")
    recorder = Recorder(routes)
    code, _ = run(tmp_path, ["--create"], environ, recorder)
    assert code == e2e.EXIT_FAIL
    assert [r.url.path for r in recorder.requests].count(mapping.UPDATE_ORDER_STATUS_PATH) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"VTP_E2E_CANCEL_RETRIES": "0"},
        {"VTP_E2E_CANCEL_RETRIES": "-1"},
        {"VTP_E2E_CANCEL_RETRIES": "abc"},
        {"VTP_E2E_CANCEL_WAIT_SECONDS": "x"},
        {"VTP_E2E_CANCEL_WAIT_SECONDS": "999"},
    ],
)
def test_bad_cancel_settings_refused_before_any_order_is_created(tmp_path, extra):
    """Verifier PR #53: a bad retry value used to surface only after create succeeded."""
    recorder = Recorder(ROUTES)
    code, _ = run(
        tmp_path, ["--create"], env(tmp_path, VTP_E2E_ALLOW_CREATE="yes", **extra), recorder
    )
    assert code == e2e.EXIT_REFUSED and recorder.requests == []


def test_cancel_server_error_is_not_retried(tmp_path):
    """Only business refusals are retried; HTTP errors fail at once."""
    routes = {**ROUTES, mapping.UPDATE_ORDER_STATUS_PATH: respond({"message": "down"}, 503)}
    environ = env(tmp_path, VTP_E2E_ALLOW_CREATE="yes", VTP_E2E_CANCEL_WAIT_SECONDS="0")
    recorder = Recorder(routes)
    code, _ = run(tmp_path, ["--create"], environ, recorder)
    assert code == e2e.EXIT_FAIL
    assert [r.url.path for r in recorder.requests].count(mapping.UPDATE_ORDER_STATUS_PATH) == 1
