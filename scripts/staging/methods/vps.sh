#!/usr/bin/env bash
# Deploy method "vps" (CR-STG-VPS): a dedicated Linux staging VPS reached over SSH, running
# the exact-SHA image as a Docker container behind the owner's HTTPS reverse proxy.
# Contract: docs/STAGING_DEPLOYMENT.md ("Deploy contract", "Method vps").
#
#   called by scripts/staging/deploy.sh <phase>     phase = migrate | start | rollback | logs
#
# Inputs (GitHub Environment `staging`; values are never printed):
#   secrets   STAGING_SSH_HOST, STAGING_SSH_USER, STAGING_SSH_PRIVATE_KEY, STAGING_SSH_KNOWN_HOSTS
#   variables STAGING_APP_DIR (absolute), optional STAGING_SSH_PORT (22), STAGING_APP_PORT (8000),
#             STAGING_EXPECTED_HOSTNAME, STAGING_HOST_DENYLIST (comma list), STAGING_DOCKER_NETWORK
#             (bridge), STAGING_PG_TOOLS_IMAGE (postgres:16), STAGING_ROLLBACK_SHA (rollback only)
#   from the dispatcher: STAGING_SHA, STAGING_IMAGE_ARCHIVE, STAGING_ENV_FILE
# Fails closed: any missing input, guard or remote failure exits non-zero.
set -euo pipefail

phase="${1:-}"
here="$(cd "$(dirname "$0")" && pwd)"
remote_script="$here/../vps/remote.sh"

fail() { echo "$1" >&2; exit "${2:-1}"; }

host="${STAGING_SSH_HOST:-}"
user="${STAGING_SSH_USER:-}"
ssh_port="${STAGING_SSH_PORT:-22}"
dir="${STAGING_APP_DIR:-}"
app_port="${STAGING_APP_PORT:-8000}"
net="${STAGING_DOCKER_NETWORK:-bridge}"
tools="${STAGING_PG_TOOLS_IMAGE:-postgres:16}"
expected_host="${STAGING_EXPECTED_HOSTNAME:-}"
rollback_to="${STAGING_ROLLBACK_SHA:-}"
tries="${STAGING_READY_TRIES:-30}"
pause="${STAGING_READY_SLEEP:-2}"

[[ "${STAGING_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || fail "STAGING_SHA must be a 40-hex commit" 2
[ -n "$host" ] || fail "STAGING_TARGET_MISSING: secret STAGING_SSH_HOST is not set" 3
[ -n "$user" ] || fail "STAGING_TARGET_MISSING: secret STAGING_SSH_USER is not set" 3
[ -n "${STAGING_SSH_PRIVATE_KEY:-}" ] || fail "STAGING_TARGET_MISSING: secret STAGING_SSH_PRIVATE_KEY is not set" 3
[ -n "${STAGING_SSH_KNOWN_HOSTS:-}" ] \
  || fail "STAGING_TARGET_MISSING: secret STAGING_SSH_KNOWN_HOSTS is not set (host key pinning is required)" 3
[ -n "$dir" ] || fail "STAGING_TARGET_MISSING: variable STAGING_APP_DIR is not set" 3

[[ "$host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$|^[0-9A-Fa-f:]+$ ]] \
  || fail "STAGING_SSH_HOST is not a plain hostname or IP address" 2
[[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || fail "STAGING_SSH_USER is not a valid user name" 2
[ "$user" != "root" ] || fail "STAGING_GUARD: STAGING_SSH_USER must be a non-root deploy user" 4
[[ "$ssh_port" =~ ^[0-9]{1,5}$ ]] && [ "$ssh_port" -ge 1 ] && [ "$ssh_port" -le 65535 ] \
  || fail "STAGING_SSH_PORT must be 1-65535" 2
[[ "$app_port" =~ ^[0-9]{1,5}$ ]] && [ "$app_port" -ge 1 ] && [ "$app_port" -le 65535 ] \
  || fail "STAGING_APP_PORT must be 1-65535" 2
[[ "$dir" =~ ^(/[A-Za-z0-9._-]+){2,}$ ]] \
  || fail "STAGING_APP_DIR must be an absolute path with at least two components (e.g. /srv/vip-staging)" 2
case "$dir/" in */./*|*/../*) fail "STAGING_APP_DIR must not contain . or .. components" 2;; esac
[[ "$net" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]] || fail "STAGING_DOCKER_NETWORK is not a valid name" 2
[[ "$tools" =~ ^[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9._-]+(@sha256:[0-9a-f]{64})?$ ]] \
  || fail "STAGING_PG_TOOLS_IMAGE must be name:tag (optionally @sha256:...)" 2
case "$tools" in *:latest|*:latest@*) fail "STAGING_PG_TOOLS_IMAGE must not use the 'latest' tag" 2;; esac
[ -z "$expected_host" ] || [[ "$expected_host" =~ ^[A-Za-z0-9.-]{1,253}$ ]] \
  || fail "STAGING_EXPECTED_HOSTNAME is not a hostname" 2
[ -z "$rollback_to" ] || [[ "$rollback_to" =~ ^[0-9a-f]{40}$ ]] || fail "STAGING_ROLLBACK_SHA must be 40-hex" 2
[[ "$tries" =~ ^[0-9]{1,3}$ ]] && [[ "$pause" =~ ^[0-9]{1,3}$ ]] || fail "bad readiness retry settings" 2

# Production guard: the owner lists production hosts/IPs; any match stops before connecting.
lower_host="$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')"
IFS=',' read -r -a denied <<< "${STAGING_HOST_DENYLIST:-}"
for d in ${denied[@]+"${denied[@]}"}; do
  d="$(printf '%s' "$d" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
  [ -n "$d" ] || continue
  [ "$d" != "$lower_host" ] || fail "PRODUCTION_GUARD: STAGING_SSH_HOST is on STAGING_HOST_DENYLIST" 4
done

if [ "$phase" = "migrate" ]; then
  grep -qx 'APP_ENV=staging' "${STAGING_ENV_FILE:?}" \
    || fail "STAGING_GUARD: STAGING_ENV_FILE does not set APP_ENV=staging" 4
fi

umask 077
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
printf '%s\n' "$STAGING_SSH_PRIVATE_KEY" > "$tmp/key"
printf '%s\n' "$STAGING_SSH_KNOWN_HOSTS" > "$tmp/known_hosts"
payload="$(base64 < "$remote_script" | tr -d '\n')"

# Every value on the remote command line was validated above; secrets travel only on stdin.
remote() {  # remote <phase>   (stdin is forwarded)
  local cmd="STG_DIR=$dir STG_PORT=$app_port STG_NETWORK=$net STG_PG_TOOLS_IMAGE=$tools"
  cmd+=" STG_EXPECTED_HOSTNAME=$expected_host STG_ROLLBACK_SHA=$rollback_to"
  cmd+=" STG_READY_TRIES=$tries STG_READY_SLEEP=$pause"
  cmd+=" bash -c \"\$(printf %s '$payload' | base64 -d)\" vip-remote $1 $STAGING_SHA"
  ssh -i "$tmp/key" -p "$ssh_port" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$tmp/known_hosts" -o GlobalKnownHostsFile=/dev/null \
    -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 \
    -- "$user@$host" "$cmd"
}

case "$phase" in
  migrate)
    [ -f "${STAGING_IMAGE_ARCHIVE:-}" ] || fail "STAGING_IMAGE_ARCHIVE missing" 2
    remote put-env < "$STAGING_ENV_FILE"
    remote load-image < "$STAGING_IMAGE_ARCHIVE"
    remote migrate < /dev/null
    ;;
  start)    remote start < /dev/null ;;
  rollback) remote rollback < /dev/null ;;
  logs)     remote logs < /dev/null ;;
  *) fail "vps: unknown phase '$phase'" 2 ;;
esac
