#!/usr/bin/env bash
# CI rehearsal of the staging pipeline mechanics (CR-STG-001): exact-SHA image, migration,
# app container, readiness, acceptance runner with --kind rehearsal. Uses an EPHEMERAL
# PostgreSQL 16 service container and throwaway secrets generated here. Its verdict is
# REHEARSAL_PASS at best - it is never staging evidence.
set -euo pipefail
: "${REHEARSAL_DB_URL:?}"   # postgresql+psycopg://... of the CI service container
sha="${GIT_SHA:?}"
image="vip-shipping-gateway:rehearsal-${sha}"
docker build --build-arg GIT_SHA="$sha" -t "$image" .

key="rehearsal-$(python -c 'import secrets;print(secrets.token_urlsafe(24))')"
hook="rehearsal-$(python -c 'import secrets;print(secrets.token_urlsafe(24))')"
digest="$(python -c 'import hashlib,sys;print(hashlib.sha256(sys.argv[1].encode()).hexdigest())' "$key")"
envfile="$(mktemp)"; chmod 600 "$envfile"
{
  echo "DATABASE_URL=${REHEARSAL_DB_URL}"
  echo "WEBHOOK_SHARED_SECRET=${hook}"
  echo "API_KEYS=rehearsal:${digest}"
  echo "VTP_TOKEN=rehearsal-no-real-vtp-call"
  echo "VTP_BASE_URL=https://partnerdev.viettelpost.vn"
  echo "LOG_FORMAT=json"
} > "$envfile"

docker run --rm --network host --env-file "$envfile" "$image" \
  alembic -c migrations/alembic.ini upgrade head
docker run -d --name rehearsal-app --network host --env-file "$envfile" "$image" >/dev/null
trap 'docker rm -f rehearsal-app >/dev/null 2>&1 || true; rm -f "$envfile"' EXIT

for _ in $(seq 1 30); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health/ready)" = "200" ] && break
  sleep 2
done
ACCEPT_API_KEY="$key" ACCEPT_WEBHOOK_SECRET="$hook" \
ACCEPT_SCAN_VARS="ACCEPT_API_KEY,ACCEPT_WEBHOOK_SECRET,REHEARSAL_DB_URL" \
  python -m scripts.staging.acceptance --base-url http://127.0.0.1:8000 --kind rehearsal \
    --expected-sha "$sha" --evidence rehearsal-evidence.json --logs-cmd "docker logs rehearsal-app"
