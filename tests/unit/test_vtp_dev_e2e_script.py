"""scripts/vtp_dev_e2e.py guards and sequence (mock HTTP only; never reaches Viettel Post)."""

import json

import httpx

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
    return {"VTP_BASE_URL": VTP_DEV_BASE_URL, "VTP_TOKEN": TOKEN,
            "VTP_E2E_SCENARIO": str(path), **extra}


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
    assert status == {"authenticate": "PASS", "get_services": "PASS", "calculate_fee": "PASS",
                      "create_shipment": "NOT_SAFE", "cancel_shipment": "SKIPPED"}
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
    code, evidence = run(tmp_path, ["--create"], env(tmp_path, VTP_E2E_ALLOW_CREATE="yes"),
                         recorder)
    assert code == e2e.EXIT_OK
    steps = {s["name"]: s for s in evidence["steps"]}
    assert steps["create_shipment"]["evidence"]["tracking_number"] == "15878180012"
    assert steps["cancel_shipment"]["evidence"] == {"tracking_number": "15878180012",
                                                    "cancelled": True}
    assert [r.url.path for r in recorder.requests][-1] == mapping.UPDATE_ORDER_STATUS_PATH


def test_failed_step_is_reported_not_raised(tmp_path):
    routes = {**ROUTES, mapping.CALCULATE_FEE_PATH: respond({"message": "down"}, 503)}
    code, evidence = run(tmp_path, [], env(tmp_path), Recorder(routes))
    assert code == e2e.EXIT_FAIL
    fee = {s["name"]: s for s in evidence["steps"]}["calculate_fee"]
    assert fee["status"] == "FAIL" and fee["error"] == "ViettelPostServerError"


def test_bad_scenario_is_refused(tmp_path):
    code, _ = run(tmp_path, [], {**env(tmp_path), "VTP_E2E_SCENARIO": str(tmp_path / "nope")})
    assert code == e2e.EXIT_REFUSED
