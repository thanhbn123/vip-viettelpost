#!/usr/bin/env bash
# Runs ON the staging VPS for deploy method "vps" (CR-STG-VPS). Never run by hand on another
# host. scripts/staging/methods/vps.sh sends this file as a base64 argument, so stdin stays
# free for the env file / image archive:
#
#   STG_DIR=... STG_PORT=... bash -c "<this script>" vip-remote <phase> <sha>
#   phase = put-env | load-image | migrate | start | rollback | logs
#
# Every phase first proves the host is the staging target (marker file, non-root, optional
# hostname) and fails closed otherwise. Secret values arrive only on stdin (put-env) and are
# never printed. Nothing is deleted except this method's own containers and temp files.
set -euo pipefail

phase="${1:-}"
sha="${2:-}"
dir="${STG_DIR:-}"
port="${STG_PORT:-}"
net="${STG_NETWORK:-bridge}"
tools="${STG_PG_TOOLS_IMAGE:-postgres:16}"
expected_host="${STG_EXPECTED_HOSTNAME:-}"
tries="${STG_READY_TRIES:-30}"
pause="${STG_READY_SLEEP:-2}"

MARKER="vip-viettelpost staging"
APP="vip-staging-app"
NEXT="vip-staging-app-next"

die() { echo "$1" >&2; exit "${2:-1}"; }
image_of() { echo "vip-shipping-gateway:staging-$1"; }

# ---- staging guard: runs for every phase, before anything is changed ----
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "remote: sha must be 40-hex" 2
[[ "$dir" =~ ^(/[A-Za-z0-9._-]+){2,}$ ]] || die "remote: bad app dir" 2
[[ "$port" =~ ^[0-9]{1,5}$ ]] || die "remote: bad port" 2
[ "$(id -u)" != "0" ] || die "STAGING_GUARD: refusing to run as root" 4
[ -f "$dir/STAGING_TARGET" ] \
  || die "STAGING_GUARD: marker $dir/STAGING_TARGET is missing - this host is not a proven staging target" 4
[ "$(head -n 1 "$dir/STAGING_TARGET" | tr -d '\r')" = "$MARKER" ] \
  || die "STAGING_GUARD: first line of $dir/STAGING_TARGET must be exactly '$MARKER'" 4
if [ -n "$expected_host" ] && [ "$(hostname)" != "$expected_host" ]; then
  die "STAGING_GUARD: hostname is not STAGING_EXPECTED_HOSTNAME" 4
fi
command -v docker >/dev/null 2>&1 || die "remote: docker is not installed or not on PATH" 1
mkdir -p "$dir/env" "$dir/backups" "$dir/state"
chmod 700 "$dir/env" "$dir/backups"

# One phase at a time on this VPS: a cancelled run's orphaned remote phase (ssh gone, script
# still running) must not interleave with the rollback step. A lock whose owner is dead is
# stale and is taken over; a live owner makes this phase fail. `logs` only reads.
if [ "$phase" != "logs" ]; then
  lock="$dir/state/lock"
  if ! mkdir "$lock" 2>/dev/null; then
    owner="$(cat "$lock/pid" 2>/dev/null || true)"
    if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then
      die "LOCKED: another deploy phase (pid $owner) is still running on this VPS" 1
    fi
    rm -rf -- "$lock"
    mkdir "$lock" || die "LOCKED: cannot take $lock" 1
  fi
  echo "$$" > "$lock/pid"
  trap 'rm -rf -- "$lock"' EXIT
fi

netargs=(--network "$net")
[ "$net" = "host" ] || netargs+=(--add-host=host.docker.internal:host-gateway)

env_file_ok() { grep -qx 'APP_ENV=staging' "$1"; }

write_state() {  # write_state <name> <value>  (atomic)
  printf '%s\n' "$2" > "$dir/state/$1.tmp"
  mv -f "$dir/state/$1.tmp" "$dir/state/$1"
}
read_state() { cat "$dir/state/$1" 2>/dev/null || true; }

# The psql/pg_dump URL: DATABASE_URL_PSQL if set, else DATABASE_URL without the "+driver".
# Evaluated inside the tools container from its env file; the value is never printed.
# shellcheck disable=SC2016  # expanded inside the tools container, on purpose
PGURL='u="${DATABASE_URL_PSQL:-$DATABASE_URL}"; u="$(printf %s "$u" | sed -E "s#^postgresql\+[a-z0-9]+://#postgresql://#")"'

# Start <sha> as the current release. On any failure the previous container is restored.
attest() {  # attest <sha>: /health 200, then /health/ready 200 reporting exactly <sha>
  local want="$1" h="" out="" code="" body="" got=""
  for _ in $(seq 1 "$tries"); do
    h="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${port}/health" || true)"
    if [ "$h" = "200" ]; then
      out="$(curl -s --max-time 5 -w '\n%{http_code}' "http://127.0.0.1:${port}/health/ready" || true)"
      code="${out##*$'\n'}"
      body="${out%$'\n'*}"
      if [ "$code" = "200" ]; then
        got="$(printf '%s' "$body" | grep -o '"version": *"[^"]*"' | head -n 1 | sed -E 's/.*"([^"]*)"$/\1/')"
        [ "$got" = "$want" ] && return 0
        echo "DEPLOYED_SHA_MISMATCH: /health/ready reports '${got:-none}', expected ${want}" >&2
        return 1
      fi
    fi
    sleep "$pause"
  done
  if [ "$h" != "200" ]; then
    echo "HEALTH_FAILED: /health returned '${h:-none}' after ${tries} tries" >&2
  else
    echo "READINESS_FAILED: /health/ready returned '${code:-none}' after ${tries} tries" >&2
  fi
  return 1
}

start_release() {
  local s="$1" img envf had_old=0
  img="$(image_of "$s")"
  envf="$dir/env/$s.env"
  docker image inspect "$img" >/dev/null 2>&1 || { echo "image $img is not on this host" >&2; return 1; }
  [ -f "$envf" ] || { echo "env file for $s is missing" >&2; return 1; }
  env_file_ok "$envf" || { echo "STAGING_GUARD: env file for $s lacks APP_ENV=staging" >&2; return 4; }
  docker rm -f "$NEXT" >/dev/null 2>&1 || true
  if docker container inspect "$APP" >/dev/null 2>&1; then
    had_old=1
    docker stop "$APP" >/dev/null
  fi
  if docker run -d --name "$NEXT" --restart unless-stopped --label "vip.sha=$s" \
       "${netargs[@]}" --env-file "$envf" -p "127.0.0.1:${port}:8000" "$img" >/dev/null \
     && attest "$s"; then
    if [ "$had_old" = 1 ]; then
      docker rm -f "$APP" >/dev/null || { echo "could not remove the previous container" >&2; return 1; }
    fi
    docker rename "$NEXT" "$APP" || { echo "could not rename $NEXT to $APP" >&2; return 1; }
    return 0
  fi
  echo "release $s did not pass health/readiness/SHA attestation; previous container restored" >&2
  docker rm -f "$NEXT" >/dev/null 2>&1 || true
  if [ "$had_old" = 1 ]; then docker start "$APP" >/dev/null; fi
  return 1
}

case "$phase" in
  put-env)
    tmp="$dir/env/.$sha.env.tmp"
    (umask 077 && cat > "$tmp")
    if ! env_file_ok "$tmp"; then
      rm -f "$tmp"
      die "STAGING_GUARD: env file lacks APP_ENV=staging" 4
    fi
    mv -f "$tmp" "$dir/env/$sha.env"
    echo "env file stored for $sha"
    ;;
  load-image)
    docker load >/dev/null
    img="$(image_of "$sha")"
    got="$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$img" 2>/dev/null \
      | sed -n 's/^APP_GIT_SHA=//p' | head -n 1)" || got=""
    [ "$got" = "$sha" ] || die "IMAGE_SHA_MISMATCH: $img carries APP_GIT_SHA='${got:-none}'" 1
    echo "image $img loaded (APP_GIT_SHA verified)"
    ;;
  migrate)
    img="$(image_of "$sha")"
    envf="$dir/env/$sha.env"
    docker image inspect "$img" >/dev/null 2>&1 || die "image $img is not on this host (load-image first)" 1
    [ -f "$envf" ] || die "env file for $sha is missing (put-env first)" 1
    env_file_ok "$envf" || die "STAGING_GUARD: env file lacks APP_ENV=staging" 4
    ver="$(docker run --rm "${netargs[@]}" --env-file "$envf" "$tools" \
      sh -c "$PGURL"'; psql "$u" -X -tA -c "show server_version_num"')" \
      || die "PG_CHECK_FAILED: cannot query the staging PostgreSQL server" 1
    ver="$(printf '%s' "$ver" | tr -d '[:space:]')"
    [[ "$ver" =~ ^16[0-9]{4}$ ]] || die "PG_VERSION_NOT_16: staging server_version_num='${ver:-none}'" 1
    backup="$dir/backups/$(date -u +%Y%m%dT%H%M%SZ)-$sha.dump"
    docker run --rm "${netargs[@]}" --env-file "$envf" "$tools" \
      sh -c "$PGURL"'; pg_dump -Fc --no-owner "$u"' > "$backup.part" \
      || { rm -f "$backup.part"; die "BACKUP_FAILED: pg_dump before migration failed" 1; }
    [ -s "$backup.part" ] || { rm -f "$backup.part"; die "BACKUP_FAILED: empty dump" 1; }
    mv -f "$backup.part" "$backup"
    echo "pre-migration backup: $backup (PostgreSQL $ver)"
    docker run --rm "${netargs[@]}" --env-file "$envf" "$img" \
      alembic -c migrations/alembic.ini upgrade head \
      || die "MIGRATION_FAILED: alembic upgrade head exited non-zero" 1
    current="$(docker run --rm "${netargs[@]}" --env-file "$envf" "$img" \
      alembic -c migrations/alembic.ini current)" || die "MIGRATION_FAILED: alembic current failed" 1
    grep -q '(head)' <<<"$current" || die "MIGRATION_NOT_AT_HEAD: ${current:-no revision}" 1
    echo "migration at head: $current"
    ;;
  start)
    prev="$(read_state current_sha)"
    start_release "$sha" || exit $?
    if [ -n "$prev" ] && [ "$prev" != "$sha" ]; then write_state previous_sha "$prev"; fi
    write_state current_sha "$sha"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) start $sha previous=${prev:-none}" >> "$dir/state/history.log"
    echo "STARTED $sha (previous ${prev:-none})"
    ;;
  rollback)
    docker rm -f "$NEXT" >/dev/null 2>&1 || true
    cur="$(read_state current_sha)"
    if [ "$cur" != "$sha" ]; then
      # start never made $sha current: the previous release is still the current one.
      if docker container inspect "$APP" >/dev/null 2>&1; then docker start "$APP" >/dev/null; fi
      echo "ROLLBACK_NOOP: $sha was never made current (current: ${cur:-none})"
      exit 0
    fi
    target="$(read_state previous_sha)"
    if [ -z "$target" ]; then
      docker stop "$APP" >/dev/null 2>&1 || true
      die "ROLLBACK_NO_PREVIOUS_RELEASE: nothing known-good before $sha; the failed release was stopped" 1
    fi
    [[ "$target" =~ ^[0-9a-f]{40}$ ]] || die "remote: rollback target must be 40-hex" 2
    # /health/ready of $target is 503 whenever $sha's migration moved the schema past
    # $target's head: that is expected, and rollback then fails (APPLICATION_ROLLBACK_ONLY).
    start_release "$target" || die "ROLLBACK_FAILED: $target did not pass health/readiness/SHA. If $sha added a migration, the schema is ahead of $target (readiness 503 by design): a person must downgrade or restore from $dir/backups (docs/STAGING.md section 5). $sha was restored." 1
    write_state current_sha "$target"
    rm -f "$dir/state/previous_sha"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) rollback $sha -> $target" >> "$dir/state/history.log"
    echo "ROLLED_BACK to $target. APPLICATION_ROLLBACK_ONLY: the database schema was NOT reverted (pre-migration dumps in $dir/backups)"
    ;;
  logs)
    docker logs --tail "${STG_LOG_LINES:-2000}" "$APP" 2>&1
    ;;
  *)
    die "remote: unknown phase '$phase'" 2
    ;;
esac
