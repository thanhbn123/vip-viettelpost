"""CR-STG-006: the VTP dev E2E job must be triggerable by an Environment variable.

GitHub evaluates a job-level ``if:`` before the job is bound to its environment, so
Environment variables (``vars.X`` set on Environment ``staging``) are invisible there. Run
36755351460 skipped the E2E although RUN_VTP_DEV_E2E=true was set on the Environment.
"""

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "staging.yml").read_text())
JOBS = WF["jobs"]


def test_no_job_level_if_reads_variables():
    for name, job in JOBS.items():
        assert "vars." not in str(job.get("if", "")), name


def test_e2e_job_follows_the_preflight_decision():
    assert JOBS["vtp-dev-e2e"]["if"] == "${{ needs.preflight.outputs.run_e2e == 'true' }}"
    assert JOBS["preflight"]["environment"] == "staging"
    assert "run_e2e" in JOBS["preflight"]["outputs"]


def g08_step():
    return next(s for s in JOBS["preflight"]["steps"] if s.get("id") == "g08")


def test_want_e2e_expression_reads_the_environment_variable_inside_the_job():
    want = g08_step()["env"]["WANT_E2E"]
    assert "vars.RUN_VTP_DEV_E2E == 'true'" in want and "inputs.run_vtp_dev_e2e" in want


@pytest.mark.parametrize(
    "preflight_rc,want,ready,run_e2e",
    [
        (0, "true", "true", "true"),
        (0, "false", "true", "false"),
        (1, "true", "false", "false"),
        (1, "false", "false", "false"),
        (0, "", "true", "false"),
    ],
)
def test_g08_step_outputs(tmp_path, preflight_rc, want, ready, run_e2e):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python").write_text(f"#!/bin/sh\nexit {preflight_rc}\n")
    (fake / "python").chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    r = subprocess.run(
        ["bash", "-e", "-c", g08_step()["run"]],
        env={"PATH": f"{fake}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out), "WANT_E2E": want},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert out.read_text().split() == [f"ready={ready}", f"run_e2e={run_e2e}"]
