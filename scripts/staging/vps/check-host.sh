#!/usr/bin/env bash
# Read-only readiness check for the staging VPS (CR-STG-004). Run ON the VPS as the deploy
# user, before the first deploy. Changes nothing; prints PASS/FAIL/INFO per item and exits 1
# when anything required for deploy method "vps" is missing. docs/VPS_STAGING_SETUP.md.
#
#   check-host.sh <app_dir> [docker_network] [pg_container] [https_base_url]
set -uo pipefail

app_dir="${1:-}"
net="${2:-bridge}"
pg="${3:-}"
base_url="${4:-}"
MARKER="vip-viettelpost staging"
fails=0

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }
info() { echo "INFO  $1"; }

if [ -z "$app_dir" ]; then
  echo "usage: check-host.sh <app_dir> [docker_network] [pg_container] [https_base_url]" >&2
  exit 2
fi

info "host: $(hostname) - confirm this is the STAGING VPS, never production"
if [ "$(id -u)" = "0" ]; then
  fail "running as root - run as the deploy user (e.g. sudo -u deploy ...)"
else
  pass "not root (user $(id -un))"
fi

for tool in bash curl base64; do
  if command -v "$tool" >/dev/null 2>&1; then pass "$tool available"; else fail "$tool missing"; fi
done

if docker info >/dev/null 2>&1; then
  pass "docker usable by $(id -un)"
else
  fail "docker not usable by $(id -un) (installed? user in group 'docker'? re-login after usermod)"
fi

if [[ ! "$app_dir" =~ ^(/[A-Za-z0-9._-]+){2,}$ ]]; then
  fail "app dir '$app_dir' must be absolute with at least two components"
elif [ ! -d "$app_dir" ]; then
  fail "app dir $app_dir does not exist"
elif [ ! -w "$app_dir" ]; then
  fail "app dir $app_dir is not writable by $(id -un)"
else
  pass "app dir $app_dir writable"
fi

if [ -f "$app_dir/STAGING_TARGET" ] && [ "$(head -n 1 "$app_dir/STAGING_TARGET" | tr -d '\r')" = "$MARKER" ]; then
  pass "marker $app_dir/STAGING_TARGET = '$MARKER'"
else
  fail "marker $app_dir/STAGING_TARGET missing or first line is not '$MARKER'"
fi

case "$net" in
  bridge|host) info "docker network: $net" ;;
  *)
    if docker network inspect "$net" >/dev/null 2>&1; then
      pass "docker network $net exists"
    else
      fail "docker network $net does not exist"
    fi
    ;;
esac

if [ -n "$pg" ]; then
  if [ "$(docker inspect -f '{{.State.Running}}' "$pg" 2>/dev/null)" = "true" ]; then
    ver="$(docker exec "$pg" postgres --version 2>/dev/null || true)"
    if [[ "$ver" =~ PostgreSQL\)\ 16\. ]]; then
      pass "PostgreSQL container $pg running: $ver"
    else
      fail "PostgreSQL container $pg is not version 16 (got '${ver:-unknown}')"
    fi
    case "$net" in
      bridge|host) ;;
      *)
        if docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$pg" 2>/dev/null \
             | tr ' ' '\n' | grep -qx "$net"; then
          pass "PostgreSQL container $pg is on network $net"
        else
          fail "PostgreSQL container $pg is not attached to network $net"
        fi
        ;;
    esac
  else
    fail "PostgreSQL container $pg is not running"
  fi
else
  info "no PostgreSQL container given - check PostgreSQL 16 by hand"
fi

if [ -n "$base_url" ]; then
  if [[ ! "$base_url" =~ ^https:// ]]; then
    fail "base url must start with https://"
  else
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$base_url/health" 2>/dev/null)"
    rc=$?
    if [ "$rc" = "0" ]; then
      pass "HTTPS reachable with a valid certificate ($base_url/health -> HTTP $code; 502 is expected before the first deploy)"
    else
      fail "HTTPS not reachable or certificate invalid ($base_url, curl exit $rc)"
    fi
  fi
else
  info "no base url given - HTTPS not checked"
fi

if [ "$fails" -gt 0 ]; then
  echo "RESULT: NOT READY ($fails failed)"
  exit 1
fi
echo "RESULT: READY for deploy method vps"
