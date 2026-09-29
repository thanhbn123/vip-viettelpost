"""Preflight reports missing names only and never reads secret values (CR-STG-001)."""

import json

from scripts.staging import preflight

ALL_SECRETS = {f"HAS_{n}": "true" for n in (*preflight.G15_SECRETS, "VTP_TOKEN")}


def test_everything_missing_lists_names_and_fails(capsys):
    assert preflight.main(["--gate", "all"], env={}) == 1
    out = capsys.readouterr().out
    for name in (
        "DATABASE_URL",
        "WEBHOOK_SHARED_SECRET",
        "API_KEYS",
        "SMOKE_API_KEY",
        "STAGING_BASE_URL",
        "STAGING_DEPLOY_METHOD",
        "VTP_E2E_SCENARIO_JSON",
        "VTP_TOKEN or secrets VTP_USERNAME + VTP_PASSWORD",
    ):
        assert name in out
    assert "STAGING_TARGET_MISSING" in out


def test_values_are_never_read_or_printed(capsys):
    env = {
        **ALL_SECRETS,
        "DATABASE_URL": "postgresql://u:" + "SuperSecret99" + "@h/db",
        "STAGING_BASE_URL": "https://staging.example.test",
        "STAGING_DEPLOY_METHOD": "nope",
        "VTP_E2E_SCENARIO_JSON": "{}",
    }
    preflight.main(["--gate", "all"], env=env)
    assert "SuperSecret99" not in capsys.readouterr().out


def test_unimplemented_method_is_invalid_until_a_hook_exists(tmp_path, monkeypatch):
    env = {
        **ALL_SECRETS,
        "STAGING_BASE_URL": "https://s.example.test",
        "STAGING_DEPLOY_METHOD": "ssh-docker",
    }
    result = preflight.check(env, "g15")
    assert not result["ok"] and any("STAGING_DEPLOY_METHOD" in i for i in result["invalid"])
    monkeypatch.setattr(preflight, "METHODS_DIR", tmp_path)
    (tmp_path / "ssh-docker.sh").write_text("#!/bin/sh\n")
    assert preflight.check(env, "g15")["ok"] is True


def test_http_url_and_bad_scenario_and_prod_vtp_are_invalid():
    env = {
        **ALL_SECRETS,
        "STAGING_BASE_URL": "http://s",
        "STAGING_DEPLOY_METHOD": "x",
        "VTP_E2E_SCENARIO_JSON": "[1]",
        "VTP_BASE_URL": "https://partner.viettelpost.vn",
    }
    invalid = " ".join(preflight.check(env, "all")["invalid"])
    assert "STAGING_BASE_URL" in invalid and "VTP_E2E_SCENARIO_JSON" in invalid
    assert "VTP_BASE_URL" in invalid


def test_g08_accepts_username_password_pair(tmp_path):
    env = {
        "HAS_VTP_USERNAME": "true",
        "HAS_VTP_PASSWORD": "true",
        "VTP_E2E_SCENARIO_JSON": json.dumps({"sender": {}}),
    }
    assert preflight.check(env, "g08")["ok"] is True
    env.pop("HAS_VTP_PASSWORD")
    assert preflight.check(env, "g08")["ok"] is False


def test_vps_is_the_only_implemented_method():
    assert preflight.implemented_methods() == ["vps"]


def test_vps_method_needs_its_ssh_inputs(capsys):
    env = {
        **ALL_SECRETS,
        "STAGING_BASE_URL": "https://s.example.test",
        "STAGING_DEPLOY_METHOD": "vps",
    }
    result = preflight.check(env, "g15")
    names = " ".join(result["missing"])
    for n in (*preflight.METHOD_REQUIREMENTS["vps"]["secrets"], "STAGING_APP_DIR"):
        assert n in names
    env.update({f"HAS_{n}": "true" for n in preflight.METHOD_REQUIREMENTS["vps"]["secrets"]})
    env["STAGING_APP_DIR"] = "/srv/vip-staging"
    assert preflight.check(env, "g15")["ok"] is True
