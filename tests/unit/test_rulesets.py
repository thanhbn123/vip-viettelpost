"""The committed rulesets encode the agreed baseline (CR-STG-002)."""

import json
from pathlib import Path

DIR = Path(__file__).resolve().parents[2] / ".github" / "rulesets"
CI_JOBS = {"lint", "test", "postgres", "image", "rehearsal"}


def load(name):
    return json.loads((DIR / name).read_text())


def rules(ruleset):
    return {r["type"]: r.get("parameters", {}) for r in ruleset["rules"]}


def checks(ruleset):
    return {
        c["context"] for c in rules(ruleset)["required_status_checks"]["required_status_checks"]
    }


def test_develop_baseline():
    rs = load("develop.json")
    assert rs["conditions"]["ref_name"]["include"] == ["refs/heads/develop"]
    assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= set(
        rules(rs)
    )
    assert checks(rs) == CI_JOBS
    assert rs["bypass_actors"] == [] and rs["enforcement"] == "active"


def test_deploy_staging_baseline():
    rs = load("deploy-staging.json")
    assert rs["conditions"]["ref_name"]["include"] == ["refs/heads/deploy/staging"]
    assert {"deletion", "non_fast_forward", "required_status_checks"} <= set(rules(rs))
    assert checks(rs) == CI_JOBS
    assert rs["bypass_actors"] == []


def test_required_checks_match_ci_job_ids():
    ci = (DIR.parent / "workflows" / "ci.yml").read_text()
    for job in CI_JOBS - {"rehearsal"}:
        assert f"\n  {job}:" in ci
