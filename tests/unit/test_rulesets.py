"""The committed rulesets encode the agreed baseline (CR-STG-002)."""

import json
import re
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


def test_main_baseline():
    """main gets the same gate as develop: no deletion, no force push, PR-only, 5 checks."""
    rs = load("main.json")
    assert rs["name"] == "main-baseline"
    assert rs["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= set(
        rules(rs)
    )
    assert checks(rs) == CI_JOBS
    assert rs["bypass_actors"] == [] and rs["enforcement"] == "active"


def test_every_protected_branch_has_a_ruleset():
    targets = {
        ref for p in DIR.glob("*.json") for ref in load(p.name)["conditions"]["ref_name"]["include"]
    }
    assert {"refs/heads/main", "refs/heads/develop", "refs/heads/deploy/staging"} <= targets


def test_required_checks_match_ci_job_ids():
    """Check-run names are the job ids (no ``name:`` key on any job)."""
    ci = (DIR.parent / "workflows" / "ci.yml").read_text()
    jobs_block = ci.split("\njobs:\n", 1)[1]
    job_ids = re.findall(r"^  ([A-Za-z0-9_-]+):$", jobs_block, re.M)
    assert CI_JOBS <= set(job_ids)
    assert not re.search(r"^    name:", jobs_block, re.M), "a job 'name:' would rename its check"


def test_drift_ignores_server_defaults_but_sees_real_changes():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "apply_rulesets", DIR.parents[1] / "scripts" / "github" / "apply_rulesets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    wanted = load("develop.json")
    declared = {k: wanted[k] for k in mod.COMPARE_KEYS}
    server = json.loads(json.dumps(wanted))
    server.update({"id": 1, "source": "thanhbn123/vip-viettelpost"})
    for rule in server["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["do_not_enforce_on_create"] = False
            rule["parameters"]["required_status_checks"].reverse()
        if rule["type"] == "pull_request":
            rule["parameters"]["allowed_merge_methods"] = ["merge", "squash", "rebase"]
    server["rules"].reverse()
    assert mod.declared_diff(declared, server) == []
    without_deletion = {**server, "rules": [r for r in server["rules"] if r["type"] != "deletion"]}
    assert mod.declared_diff(declared, without_deletion) != []
    weaker = json.loads(json.dumps(server))
    for rule in weaker["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["required_status_checks"].pop()
    assert mod.declared_diff(declared, weaker) != []
    # A rule added on the server only (e.g. someone adds "creation" in the UI) is drift too.
    extra = {**server, "rules": [*server["rules"], {"type": "creation"}]}
    assert "/rules (rule types)" in mod.declared_diff(declared, extra)
