"""The replay-webhooks helper that a systemd timer drives.

This exists because the first version of this command was an inline ExecStart= line in a
runbook, and it was wrong: systemd expands ``$sha`` itself, so the variable reached bash
empty and the unit would have failed on its first fire. Nothing could have caught that,
because an ExecStart line in a Markdown file is not executed by anything. A script is.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "staging" / "vps" / "replay-webhooks.sh"
SHA = "a" * 40

FAKE_DOCKER = """#!/bin/bash
printf '%s\\n' "$*" >> "$FAKE_STATE/docker.argv"
exit "${FAKE_DOCKER_RC:-0}"
"""


@pytest.fixture
def host(tmp_path):
    """A fake staging host: app dir, marker, env file, recorded release."""
    app = tmp_path / "srv"
    (app / "state").mkdir(parents=True)
    (app / "env").mkdir()
    (app / "STAGING_TARGET").write_text("vip-viettelpost staging\n")
    (app / "state" / "current_sha").write_text(SHA + "\n")
    (app / "env" / f"{SHA}.env").write_text("APP_ENV=staging\nDATABASE_URL=sqlite://\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)

    state = tmp_path / "state"
    state.mkdir()

    class Host:
        app_dir = app
        def run(self, **over):
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_STATE": str(state),
                "STAGING_APP_DIR": str(app),
                **over,
            }
            return subprocess.run(
                ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
            )

        def docker_argv(self):
            f = state / "docker.argv"
            return f.read_text() if f.exists() else ""

    return Host()


def test_runs_the_image_of_the_release_that_is_live(host):
    r = host.run()
    assert r.returncode == 0, r.stderr
    argv = host.docker_argv()
    # The bug this file exists for: an empty sha would produce "staging-" and "/env/.env".
    assert f"vip-shipping-gateway:staging-{SHA}" in argv
    assert f"{SHA}.env" in argv and "/env/.env" not in argv
    assert "python -m app.jobs.replay_webhooks" in argv


def test_exit_code_of_the_job_is_passed_through(host):
    """3 means "ran, but events are still unattached" -- the state a person must see."""
    assert host.run(FAKE_DOCKER_RC="3").returncode == 3


@pytest.mark.parametrize(
    "break_it,marker",
    [
        (lambda a: (a / "STAGING_TARGET").unlink(), "REPLAY_GUARD"),
        (lambda a: (a / "state" / "current_sha").unlink(), "no release recorded"),
        (lambda a: (a / "state" / "current_sha").write_text("not-a-sha\n"), "not a commit sha"),
        (lambda a: (a / "state" / "current_sha").write_text("\n"), "not a commit sha"),
        (lambda a: (a / "env" / f"{SHA}.env").unlink(), "env file for the live release"),
        (
            lambda a: (a / "env" / f"{SHA}.env").write_text("APP_ENV=production\n"),
            "STAGING_GUARD",
        ),
    ],
)
def test_refuses_to_run_against_anything_it_cannot_identify(host, break_it, marker):
    break_it(host.app_dir)
    r = host.run()
    assert r.returncode != 0 and marker in r.stderr
    assert host.docker_argv() == "", "nothing may be started once a guard has tripped"


def test_script_is_executable():
    assert stat.S_IMODE(SCRIPT.stat().st_mode) & stat.S_IXUSR
