"""scripts/staging/deploy.sh contract (CR-STG-001): fails closed without a committed hook."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "staging" / "deploy.sh"


def run(args, env):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={"PATH": "/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_no_method_is_target_missing():
    r = run(["migrate"], {})
    assert r.returncode == 3 and "STAGING_TARGET_MISSING" in r.stderr


def test_unknown_method_is_target_missing():
    r = run(["start"], {"STAGING_DEPLOY_METHOD": "ssh-docker", "STAGING_SHA": "a" * 40})
    assert r.returncode == 3 and "no hook for method 'ssh-docker'" in r.stderr


def test_invalid_method_name_and_phase():
    assert run(["start"], {"STAGING_DEPLOY_METHOD": "../../etc"}).returncode == 3
    assert run(["destroy"], {"STAGING_DEPLOY_METHOD": "x"}).returncode == 2
