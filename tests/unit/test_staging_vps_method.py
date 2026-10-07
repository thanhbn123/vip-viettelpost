"""Deploy method ``vps`` (CR-STG-VPS), exercised through the real dispatcher with a fake
transport: ``ssh`` runs the remote command locally, ``docker``/``curl``/``id``/``hostname``
are fakes that keep state in a temp dir. No network, no real VPS, no real Docker."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.staging import preflight

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "scripts" / "staging" / "deploy.sh"
SHA_A = "a" * 40
SHA_B = "b" * 40
KEY = "fake-test-ssh-key\nKEYMATERIAL-9f3e1\nfake-test-ssh-key-end"
DB_SECRET = "DBSECRET-fake-7c1d44"
HOOK_SECRET = "HOOKSECRET-fake-51ab"
MARKER = "vip-viettelpost staging\n"

FAKE_SSH = r"""#!/bin/bash
# Fake ssh: record argv + key file mode, then run the remote command locally.
args=("$@"); i=0; key=""
while [ $i -lt ${#args[@]} ]; do
  [ "${args[$i]}" = "-i" ] && key="${args[$((i+1))]}"
  [ "${args[$i]}" = "--" ] && break
  i=$((i+1))
done
printf '%s\n' "$@" >> "$FAKE_STATE/ssh.argv"
ls -l "$key" | cut -c1-10 >> "$FAKE_STATE/ssh.keymode"
# The remote command runs under a POSIX login shell (dash on Ubuntu), like a real VPS.
exec sh -c "${args[$((i+2))]}"
"""

FAKE_BASE64 = r"""#!/bin/bash
# Pass-through base64 that can simulate a broken or empty decode on the "VPS".
case "$*" in *-d*)
  [ -n "${FAKE_BASE64_DECODE_FAIL:-}" ] && { echo "base64: invalid input" >&2; exit 1; }
  [ -n "${FAKE_BASE64_DECODE_EMPTY:-}" ] && { cat >/dev/null; exit 0; }
esac
exec /usr/bin/base64 "$@"
"""

FAKE_DOCKER = r"""#!/bin/bash
# Fake docker with state under $FAKE_STATE/docker.
d="$FAKE_STATE/docker"; mkdir -p "$d/images" "$d/containers"
echo "$*" >> "$FAKE_STATE/docker.log"
all="$*"
safe() { printf '%s' "$1" | tr '/:' '__'; }
case "$1" in
  load)
    tag=""; sha=""
    while IFS= read -r line; do
      case "$line" in TAG=*) tag="${line#TAG=}";; SHA=*) sha="${line#SHA=}";; esac
    done
    [ -n "$tag" ] || exit 1
    echo "$sha" > "$d/images/$(safe "$tag")"; exit 0;;
  image)
    img="${!#}"; f="$d/images/$(safe "$img")"
    [ -f "$f" ] || exit 1
    case "$all" in *--format*) echo "PATH=/usr/bin"; echo "APP_GIT_SHA=$(cat "$f")";; esac
    exit 0;;
  container) [ -f "$d/containers/$3" ]; exit $?;;
  stop|start)
    f="$d/containers/$2"; [ -f "$f" ] || exit 1
    if [ "$1" = stop ]; then sed -i.bak 's/^running /stopped /' "$f"
    else sed -i.bak 's/^stopped /running /' "$f"; fi
    exit 0;;
  rm)    rm -f "$d/containers/${!#}"; exit 0;;
  rename) mv "$d/containers/$2" "$d/containers/$3"; exit 0;;
  logs)  echo '{"level":"info","request_id":"accept-x"}'; exit 0;;
  run)
    case "$all" in
      *" -d "*)
        [ -n "${FAKE_RUN_FAIL:-}" ] && exit 1
        name=""; sha=""; prev=""
        for a in "$@"; do
          [ "$prev" = "--name" ] && name="$a"
          case "$a" in vip.sha=*) sha="${a#vip.sha=}";; esac
          prev="$a"
        done
        echo "running $sha" > "$d/containers/$name"; echo "cid-$name"; exit 0;;
      *pg_restore*--list*)
        cat >/dev/null
        if [ -n "${FAKE_PG_RESTORE_FAIL:-}" ]; then
          echo "pg_restore: error: did not find magic string" >&2; exit 1
        fi
        [ -n "${FAKE_PG_RESTORE_EMPTY:-}" ] && exit 0
        # Real pg_restore emits a TABLE entry and a separate TABLE DATA entry per table.
        printf '%s\n' "215; 1259 16400 TABLE public shipments vip" \
          "3012; 0 16400 TABLE DATA public shipments vip" \
          "3100; 0 0 TABLE ATTACH public shipments_2026 vip" \
          "2890; 2606 16420 CONSTRAINT public shipments shipments_pkey vip"
        exit 0;;
      *"show server_version_num"*) echo "${FAKE_PG_VERSION:-160004}"; exit "${FAKE_PG_RC:-0}";;
      *pg_dump*) echo "PGDMP-fake"; exit "${FAKE_DUMP_RC:-0}";;
      *"from pg_tables"*) echo "${FAKE_TABLE_COUNT:-1}"; exit "${FAKE_TABLE_COUNT_RC:-0}";;
      *"upgrade head"*) exit "${FAKE_MIGRATE_RC:-0}";;
      *"alembic"*current*) echo "${FAKE_ALEMBIC_CURRENT:-shp_0004 (head)}"; exit 0;;
    esac
    exit 0;;
esac
exit 0
"""

FAKE_CURL = r"""#!/bin/bash
# Fake curl: answers for the running container (next first, else app).
d="$FAKE_STATE/docker/containers"; sha=""
for n in vip-staging-app-next vip-staging-app; do
  if [ -f "$d/$n" ] && grep -q '^running ' "$d/$n"; then sha="$(cut -d' ' -f2 "$d/$n")"; break; fi
done
url="${!#}"; code=000; body=""
if [ -n "$sha" ]; then
  case "$url" in
    */health/ready)
      code=200; [ "$sha" = "${FAKE_READY_FAIL_SHA:-}" ] && code=503
      v="$sha"; [ "$sha" = "${FAKE_WRONG_VERSION_SHA:-}" ] && v="$(printf '0%.0s' {1..40})"
      body="{\"status\":\"ready\",\"checks\":{},\"version\":\"$v\"}";;
    */health)
      code=200; [ "$sha" = "${FAKE_HEALTH_FAIL_SHA:-}" ] && code=500; body='{"status":"ok"}';;
  esac
fi
case "$*" in
  *"-o /dev/null"*) printf '%s' "$code";;
  *) printf '%s\n%s' "$body" "$code";;
esac
"""


@pytest.fixture
def stg(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "ssh": FAKE_SSH,
        "docker": FAKE_DOCKER,
        "curl": FAKE_CURL,
        "base64": FAKE_BASE64,
        "id": '#!/bin/bash\necho "${FAKE_UID:-1000}"\n',
        "hostname": '#!/bin/bash\necho "${FAKE_HOSTNAME:-stg-box}"\n',
    }.items():
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    app_dir = tmp_path / "srv" / "vip-staging"
    app_dir.mkdir(parents=True)
    (app_dir / "STAGING_TARGET").write_text(MARKER)
    env_file = tmp_path / "staging.env"
    # Built by concatenation so the repository secret tripwire does not see a literal URL.
    db_url = "postgresql+psycopg://u:" + DB_SECRET + "@db/stg"
    env_file.write_text(
        "DATABASE_URL=" + db_url + "\nWEBHOOK_SHARED_SECRET=" + HOOK_SECRET + "\nAPP_ENV=staging\n"
    )
    env_file.chmod(0o600)

    class Stg:
        path = tmp_path
        app = app_dir

        def env(self, sha, **over):
            archive = tmp_path / f"image-{sha[:6]}.tar.gz"
            archive.write_text(f"TAG=vip-shipping-gateway:staging-{sha}\nSHA={sha}\n")
            e = {
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "HOME": str(tmp_path),
                "FAKE_STATE": str(state),
                "STAGING_DEPLOY_METHOD": "vps",
                "STAGING_SHA": sha,
                "STAGING_IMAGE_ARCHIVE": str(archive),
                "STAGING_ENV_FILE": str(env_file),
                "STAGING_SSH_HOST": "stg.example.test",
                "STAGING_SSH_USER": "deploy",
                "STAGING_SSH_PRIVATE_KEY": KEY,
                "STAGING_SSH_KNOWN_HOSTS": "stg.example.test ssh-ed25519 AAAAC3NzaFAKE",
                "STAGING_APP_DIR": str(app_dir),
                "STAGING_READY_TRIES": "2",
                "STAGING_READY_SLEEP": "0",
            }
            e.update({k: v for k, v in over.items() if v is not None})
            for k in [k for k, v in over.items() if v is None]:
                e.pop(k, None)
            return e

        def run(self, phase, sha, **over):
            return subprocess.run(
                ["bash", str(DISPATCHER), phase],
                env=self.env(sha, **over),
                capture_output=True,
                text=True,
                timeout=60,
            )

        def deploy(self, sha, **over):
            m = self.run("migrate", sha, **over)
            assert m.returncode == 0, m.stderr
            return self.run("start", sha, **over)

        def container(self, name="vip-staging-app"):
            f = state / "docker" / "containers" / name
            return f.read_text().split() if f.exists() else None

        def state_file(self, name):
            f = app_dir / "state" / name
            return f.read_text().strip() if f.exists() else None

        def log(self, name):
            f = state / name
            return f.read_text() if f.exists() else ""

        env_path = env_file

    return Stg()


# 1 + 17: allowlisted, and the other contract paths are unchanged
def test_vps_is_the_allowlisted_method_and_others_still_fail_closed(stg):
    assert preflight.implemented_methods() == ["vps"]
    r = stg.run("start", SHA_A, STAGING_DEPLOY_METHOD="ssh-docker")
    assert r.returncode == 3 and "no hook for method 'ssh-docker'" in r.stderr
    assert "implemented: vps" in r.stderr
    assert not (stg.path / "state" / "ssh.argv").exists()


# 2, 3, 4 (+ known_hosts, app dir)
@pytest.mark.parametrize(
    "missing",
    [
        "STAGING_SSH_HOST",
        "STAGING_SSH_USER",
        "STAGING_SSH_PRIVATE_KEY",
        "STAGING_SSH_KNOWN_HOSTS",
        "STAGING_APP_DIR",
    ],
)
def test_missing_input_fails_before_connecting(stg, missing):
    r = stg.run("migrate", SHA_A, **{missing: None})
    assert r.returncode == 3 and "STAGING_TARGET_MISSING: " in r.stderr and missing in r.stderr
    assert stg.log("ssh.argv") == ""


@pytest.mark.parametrize(
    "var,value",
    [
        ("STAGING_SSH_USER", "root"),
        ("STAGING_APP_DIR", "/"),
        ("STAGING_APP_DIR", "/srv"),
        ("STAGING_APP_DIR", "/srv/../etc"),
        ("STAGING_APP_DIR", "relative/dir"),
        ("STAGING_SSH_HOST", "host;rm -rf /"),
        ("STAGING_SSH_PORT", "0"),
        ("STAGING_PG_TOOLS_IMAGE", "postgres:latest"),
        ("STAGING_PG_TOOLS_IMAGE", "postgres"),
    ],
)
def test_unsafe_inputs_are_refused_before_connecting(stg, var, value):
    r = stg.run("migrate", SHA_A, **{var: value})
    assert r.returncode in (2, 4), r.stderr
    assert stg.log("ssh.argv") == ""


# 5
def test_missing_marker_fails_closed_without_changes(stg):
    (stg.app / "STAGING_TARGET").unlink()
    r = stg.run("migrate", SHA_A)
    assert r.returncode == 4 and "STAGING_TARGET is missing" in r.stderr
    assert "load" not in stg.log("docker.log") and "run" not in stg.log("docker.log")
    assert not (stg.app / "env").exists()


# 6
def test_wrong_marker_hostname_or_app_env_fails_closed(stg):
    (stg.app / "STAGING_TARGET").write_text("vip-viettelpost production\n")
    r = stg.run("migrate", SHA_A)
    assert r.returncode == 4 and "STAGING_GUARD" in r.stderr
    (stg.app / "STAGING_TARGET").write_text(MARKER)
    r = stg.run("migrate", SHA_A, STAGING_EXPECTED_HOSTNAME="stg-box-2")
    assert r.returncode == 4 and "hostname" in r.stderr
    r = stg.run("start", SHA_A, FAKE_UID="0")
    assert r.returncode == 4 and "root" in r.stderr
    text = stg.env_path.read_text()
    stg.env_path.write_text(text.replace("APP_ENV=staging", "APP_ENV=production"))
    r = stg.run("migrate", SHA_A)
    assert r.returncode == 4 and "APP_ENV=staging" in r.stderr
    assert stg.log("docker.log") == ""


# 16
def test_production_guard_denylist_stops_before_ssh(stg):
    r = stg.run("migrate", SHA_A, STAGING_HOST_DENYLIST="prod.example.test, STG.example.test")
    assert r.returncode == 4 and "PRODUCTION_GUARD" in r.stderr
    assert stg.log("ssh.argv") == ""
    assert stg.deploy(SHA_A, STAGING_HOST_DENYLIST="prod.example.test").returncode == 0


# 7, 8
def test_exact_sha_is_propagated_and_latest_is_never_used(stg):
    r = stg.deploy(SHA_A)
    assert r.returncode == 0, r.stderr
    assert f"STARTED {SHA_A}" in r.stdout
    assert stg.container() == ["running", SHA_A]
    assert stg.state_file("current_sha") == SHA_A
    docker = stg.log("docker.log")
    assert f"vip-shipping-gateway:staging-{SHA_A}" in docker
    assert f"vip.sha={SHA_A}" in docker
    assert "latest" not in docker and "latest" not in stg.log("ssh.argv")
    assert "127.0.0.1:8000:8000" in docker and "--env-file" in docker
    assert list((stg.app / "backups").glob(f"*-{SHA_A}.dump"))
    assert oct(stat.S_IMODE(os.stat(stg.app / "env" / f"{SHA_A}.env").st_mode)) == "0o600"


def test_pre_migration_dump_is_read_back_before_migrating(stg):
    """M1: the rollback contract leans on this dump, so size alone is not evidence."""
    r = stg.run("migrate", SHA_A)
    assert r.returncode == 0, r.stderr
    assert "pg_restore --list" in r.stdout
    assert "4 archive entries, ~1 table(s)" in r.stdout  # ATTACH/DATA are not tables
    docker = stg.log("docker.log")
    assert docker.index("pg_restore --list") < docker.index("upgrade head")


def test_successful_migrate_leaves_only_the_finished_dump(stg):
    """No .part and no .err may survive a good run either."""
    assert stg.run("migrate", SHA_A).returncode == 0
    left = sorted(p.name.split("-", 1)[1] for p in (stg.app / "backups").glob("*"))
    assert left == [f"{SHA_A}.dump"]


def test_image_whose_embedded_sha_differs_is_rejected(stg):
    e = stg.env(SHA_A)
    Path(e["STAGING_IMAGE_ARCHIVE"]).write_text(
        f"TAG=vip-shipping-gateway:staging-{SHA_A}\nSHA={SHA_B}\n"
    )
    r = subprocess.run(
        ["bash", str(DISPATCHER), "migrate"], env=e, capture_output=True, text=True, timeout=60
    )
    assert r.returncode != 0 and "IMAGE_SHA_MISMATCH" in r.stderr
    assert "upgrade head" not in stg.log("docker.log")


# 9
@pytest.mark.parametrize(
    "over,marker",
    [
        ({"FAKE_MIGRATE_RC": "1"}, "MIGRATION_FAILED"),
        ({"FAKE_ALEMBIC_CURRENT": "shp_0003"}, "MIGRATION_NOT_AT_HEAD"),
        ({"FAKE_PG_VERSION": "150008"}, "PG_VERSION_NOT_16"),
        ({"FAKE_DUMP_RC": "1"}, "BACKUP_FAILED"),
        # M1: a dump that is non-empty but not restorable, and one that silently lost the
        # tables, must both stop the deploy -- the rollback contract leans on this file.
        ({"FAKE_PG_RESTORE_FAIL": "1"}, "BACKUP_UNREADABLE"),
        ({"FAKE_PG_RESTORE_EMPTY": "1"}, "BACKUP_INCOMPLETE"),
        # N3: the table count failing must not leave an unverified .part behind either.
        ({"FAKE_TABLE_COUNT_RC": "1"}, "PG_CHECK_FAILED"),
    ],
)
def test_migration_problems_fail_the_phase(stg, over, marker):
    r = stg.run("migrate", SHA_A, **over)
    assert r.returncode != 0 and marker in r.stderr
    if marker != "MIGRATION_NOT_AT_HEAD":
        assert "upgrade head" not in stg.log("docker.log") or marker == "MIGRATION_FAILED"
    if marker.startswith("BACKUP_") or marker == "PG_CHECK_FAILED":
        # Nothing that was not verified may stay in backups/ looking like a backup.
        assert not list((stg.app / "backups").glob("*")), "a rejected dump must not be kept"


# 10, 11, 12: a failing release never becomes current and the previous one keeps running
@pytest.mark.parametrize(
    "over,marker",
    [
        ({"FAKE_HEALTH_FAIL_SHA": SHA_B}, "HEALTH_FAILED"),
        ({"FAKE_READY_FAIL_SHA": SHA_B}, "READINESS_FAILED"),
        ({"FAKE_WRONG_VERSION_SHA": SHA_B}, "DEPLOYED_SHA_MISMATCH"),
    ],
)
def test_start_failure_propagates_and_keeps_previous_release(stg, over, marker):
    assert stg.deploy(SHA_A).returncode == 0
    r = stg.deploy(SHA_B, **over)
    assert r.returncode != 0 and marker in r.stderr
    assert stg.container() == ["running", SHA_A]
    assert stg.container("vip-staging-app-next") is None
    assert stg.state_file("current_sha") == SHA_A
    rb = stg.run("rollback", SHA_B)
    assert rb.returncode == 0 and "ROLLBACK_NOOP" in rb.stdout
    assert stg.container() == ["running", SHA_A]


# 13 + 14: acceptance failed after B went live -> workflow calls rollback -> exact previous A
def test_rollback_after_acceptance_failure_restores_exact_previous_sha(stg):
    assert stg.deploy(SHA_A).returncode == 0
    assert stg.deploy(SHA_B).returncode == 0
    assert stg.container() == ["running", SHA_B]
    assert stg.state_file("previous_sha") == SHA_A
    rb = stg.run("rollback", SHA_B)
    assert rb.returncode == 0, rb.stderr
    assert f"ROLLED_BACK to {SHA_A}" in rb.stdout and "APPLICATION_ROLLBACK_ONLY" in rb.stdout
    assert stg.container() == ["running", SHA_A]
    assert stg.state_file("current_sha") == SHA_A
    assert "downgrade" not in stg.log("docker.log")


def test_first_release_without_previous_is_stopped_and_reported(stg):
    assert stg.deploy(SHA_A).returncode == 0
    rb = stg.run("rollback", SHA_A)
    assert rb.returncode != 0 and "ROLLBACK_NO_PREVIOUS_RELEASE" in rb.stderr
    assert stg.container() == ["stopped", SHA_A]


def test_rollback_target_that_fails_attestation_is_reported(stg):
    assert stg.deploy(SHA_A).returncode == 0
    assert stg.deploy(SHA_B).returncode == 0
    # e.g. B added a migration: A's readiness is 503 by design (schema ahead of A's head)
    rb = stg.run("rollback", SHA_B, FAKE_READY_FAIL_SHA=SHA_A)
    assert rb.returncode != 0 and "ROLLBACK_FAILED" in rb.stderr and "migration" in rb.stderr
    assert stg.container() == ["running", SHA_B]  # the failed release is restored, job stays red


# 15
def test_secrets_never_reach_the_command_line_or_output(stg):
    r = stg.deploy(SHA_A)
    logs = stg.run("logs", SHA_A)
    assert r.returncode == 0 and logs.returncode == 0 and "request_id" in logs.stdout
    seen = stg.log("ssh.argv") + stg.log("docker.log") + r.stdout + r.stderr + logs.stdout
    for secret in ("KEYMATERIAL-9f3e1", DB_SECRET, HOOK_SECRET):
        assert secret not in seen
    argv = stg.log("ssh.argv")
    assert "StrictHostKeyChecking=yes" in argv and "BatchMode=yes" in argv
    assert "StrictHostKeyChecking=no" not in argv
    assert set(stg.log("ssh.keymode").split()) == {"-rw-------"}
    # the temporary key/known_hosts directory is removed after every call
    keys = [ln for ln in argv.splitlines() if ln.endswith("/key")]
    assert keys and not any(Path(k).exists() for k in keys)


def test_workflow_passes_vps_inputs_only_to_deploy_steps():
    wf = (ROOT / ".github" / "workflows" / "staging.yml").read_text()
    deploy_job = wf.split("\n  deploy:\n", 1)[1]
    for name in ("STAGING_SSH_PRIVATE_KEY", "STAGING_SSH_KNOWN_HOSTS", "STAGING_APP_DIR"):
        assert name in deploy_job
    assert "continue-on-error" not in deploy_job
    assert "environment: staging" in deploy_job
    head = wf.split("\n  deploy:\n", 1)[0]
    image_job = head.split("\n  image:\n", 1)[1].split("\n  vtp-dev-e2e:\n", 1)[0]
    assert "secrets." not in image_job


# verifier PR #36 MED-1: a broken bootstrap on the VPS must never look like success
@pytest.mark.parametrize("fault", ["FAKE_BASE64_DECODE_FAIL", "FAKE_BASE64_DECODE_EMPTY"])
@pytest.mark.parametrize("phase", ["migrate", "start", "rollback"])
def test_remote_bootstrap_failure_is_not_success(stg, fault, phase):
    r = stg.run(phase, SHA_A, **{fault: "1"})
    assert r.returncode == 97 and "REMOTE_BOOTSTRAP_FAILED" in r.stderr
    assert stg.log("docker.log") == ""


def test_host_network_requires_the_container_port(stg):
    r = stg.run("migrate", SHA_A, STAGING_DOCKER_NETWORK="host", STAGING_APP_PORT="9000")
    assert r.returncode == 2 and "STAGING_APP_PORT must be 8000" in r.stderr
    assert stg.log("ssh.argv") == ""


def test_live_lock_blocks_a_second_phase_and_stale_lock_is_taken_over(stg):
    lock = stg.app / "state" / "lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))  # a live process holds it
    r = stg.run("start", SHA_A)
    assert r.returncode != 0 and "LOCKED" in r.stderr
    assert "run" not in stg.log("docker.log")
    dead = subprocess.run(["sh", "-c", "echo $$"], capture_output=True, text=True).stdout.strip()
    (lock / "pid").write_text(dead)
    assert stg.deploy(SHA_A).returncode == 0
    assert not lock.exists()
