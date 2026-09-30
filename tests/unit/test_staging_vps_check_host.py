"""scripts/staging/vps/check-host.sh (CR-STG-004): read-only VPS readiness check, run with
fake docker/curl/id/hostname so no real VPS or Docker is needed."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.staging import preflight

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "staging" / "vps" / "check-host.sh"

FAKE_DOCKER = r"""#!/bin/bash
echo "$*" >> "$FAKE_LOG"
case "$1" in
  info) [ -z "${FAKE_NO_DOCKER:-}" ]; exit $?;;
  network) [ "$3" = "${FAKE_NET:-vip-staging}" ]; exit $?;;
  inspect)
    case "$*" in
      *State.Running*) [ -n "${FAKE_PG_DOWN:-}" ] && echo false || echo true;;
      *Networks*) echo "${FAKE_PG_NETS:-vip-staging}";;
    esac
    exit 0;;
  exec) echo "postgres (PostgreSQL) ${FAKE_PG_VER:-16.4 (Debian 16.4-1.pgdg120+2)}"; exit 0;;
esac
exit 0
"""

FAKE_CURL = r"""#!/bin/bash
echo "curl $*" >> "$FAKE_LOG"
case "$*" in
  *--resolve*) [ -n "${FAKE_LOCAL_TLS_FAIL:-}" ] && exit 60;;
  *) [ -n "${FAKE_TLS_FAIL:-}" ] && exit 6;;
esac
printf '502'
"""


@pytest.fixture
def host(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "docker": FAKE_DOCKER,
        "curl": FAKE_CURL,
        "id": '#!/bin/bash\n[ "$1" = -u ] && echo "${FAKE_UID:-1000}" || echo deploy\n',
        "hostname": "#!/bin/bash\necho stg-box\n",
    }.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    app = tmp_path / "srv" / "vip-staging"
    app.mkdir(parents=True)
    (app / "STAGING_TARGET").write_text("vip-viettelpost staging\n")
    log = tmp_path / "docker.log"

    def run(*args, **env):
        e = {"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_LOG": str(log), **env}
        return subprocess.run(
            ["bash", str(SCRIPT), *args], env=e, capture_output=True, text=True, timeout=30
        )

    run.app = app
    run.log = log
    return run


FULL = ("vip-staging", "vip-staging-pg", "https://stg.example.test")


def test_ready_host_passes(host):
    r = host(str(host.app), *FULL)
    assert r.returncode == 0, r.stdout
    assert "RESULT: READY" in r.stdout and "FAIL" not in r.stdout
    assert "PostgreSQL) 16." in r.stdout


@pytest.mark.parametrize(
    "env,expect",
    [
        ({"FAKE_UID": "0"}, "running as root"),
        ({"FAKE_NO_DOCKER": "1"}, "docker not usable"),
        ({"FAKE_NET": "other"}, "network vip-staging does not exist"),
        ({"FAKE_PG_DOWN": "1"}, "is not running"),
        ({"FAKE_PG_VER": "15.8"}, "is not version 16"),
        ({"FAKE_PG_NETS": "bridge"}, "not attached to network vip-staging"),
        ({"FAKE_TLS_FAIL": "1"}, "not reachable via public DNS"),
        ({"FAKE_LOCAL_TLS_FAIL": "1"}, "this host does not serve valid HTTPS"),
    ],
)
def test_each_missing_prerequisite_fails(host, env, expect):
    r = host(str(host.app), *FULL, **env)
    assert r.returncode == 1 and expect in r.stdout and "RESULT: NOT READY" in r.stdout


def test_marker_and_app_dir_are_checked(host):
    (host.app / "STAGING_TARGET").write_text("vip-viettelpost production\n")
    r = host(str(host.app), *FULL)
    assert r.returncode == 1 and "marker" in r.stdout
    r = host("/srv", *FULL)
    assert r.returncode == 1 and "at least two components" in r.stdout
    r = host(str(host.app / "missing"), *FULL)
    assert r.returncode == 1 and "does not exist" in r.stdout
    assert host().returncode == 2


def test_http_base_url_is_refused(host):
    r = host(str(host.app), "vip-staging", "vip-staging-pg", "http://stg.example.test")
    assert r.returncode == 1 and "must be https://<hostname>" in r.stdout


def test_check_is_read_only(host):
    host(str(host.app), *FULL)
    calls = host.log.read_text().split("\n")
    verbs = {c.split(" ")[0] for c in calls if c}
    assert verbs <= {"info", "network", "inspect", "exec", "curl"}
    assert "--resolve stg.example.test:443:127.0.0.1" in host.log.read_text()
    assert not any(c.startswith(("run", "rm", "stop", "start", "pull", "load")) for c in calls)
    assert sorted(p.name for p in host.app.iterdir()) == ["STAGING_TARGET"]


# --- docs/VPS_STAGING_SETUP.md: commands parse, no literal placeholders, names match code ---
RUNBOOK = ROOT / "docs" / "VPS_STAGING_SETUP.md"


def runbook_blocks():
    """(section letter, command) for every fenced bash block under ## A/B/C/D."""
    section, out = None, []
    text = RUNBOOK.read_text()
    for part in re.split(r"^(## .*)$", text, flags=re.M):
        m = re.match(r"^## ([A-D])\. ", part)
        if m:
            section = m.group(1)
            continue
        if part.startswith("## "):
            section = None
            continue
        for block in re.findall(r"```bash\n(.*?)```", part, flags=re.S):
            out.append((section, block))
    return out


def test_runbook_blocks_parse_in_the_right_shell():
    blocks = runbook_blocks()
    assert {s for s, _ in blocks} >= {"A", "B", "C"}
    checked = {"zsh": 0, "bash": 0}
    for section, cmd in blocks:
        # A/C run on the MacBook (zsh); B runs on the VPS (bash). CI has no zsh: the
        # bash blocks are still checked there, the zsh ones only where zsh exists.
        shell = "zsh" if section in ("A", "C") else "bash"
        if shutil.which(shell) is None:
            continue
        r = subprocess.run([shell, "-n"], input=cmd, capture_output=True, text=True)
        assert r.returncode == 0, (section, cmd, r.stderr)
        checked[shell] += 1
    assert checked["bash"] >= 8


def test_runbook_has_no_literal_placeholders_to_paste():
    # The owner once pasted `ssh <user-admin>@<ip...>` literally (zsh parse error).
    for _, cmd in runbook_blocks():
        assert not re.search(r"<[a-z][a-z0-9_-]*>", cmd, flags=re.I), cmd


def test_runbook_names_match_code():
    text = RUNBOOK.read_text()
    required = (
        *preflight.G15_SECRETS,
        *preflight.METHOD_REQUIREMENTS["vps"]["secrets"],
        *preflight.METHOD_REQUIREMENTS["vps"]["variables"],
        "STAGING_BASE_URL",
        "STAGING_DEPLOY_METHOD",
        "VTP_E2E_SCENARIO_JSON",
        "VTP_TOKEN",
        "VTP_USERNAME",
        "VTP_PASSWORD",
    )
    for name in required:
        assert f"`{name}`" in text or f" {name} " in text, name
    # every variable the runbook sets is one the staging workflow actually reads
    workflow = (ROOT / ".github" / "workflows" / "staging.yml").read_text()
    variables = re.findall(r"gh variable set ([A-Z_]+)", text)
    secrets = re.findall(r"gh secret set ([A-Z_]+)", text)
    assert len(variables) >= 6 and len(secrets) >= 10
    for name in variables:
        assert f"vars.{name}" in workflow, name
    for name in secrets:
        assert f"secrets.{name}" in workflow, name
