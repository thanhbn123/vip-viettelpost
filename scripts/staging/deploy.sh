#!/usr/bin/env bash
# Staging deploy dispatcher (CR-STG-001). Contract: docs/STAGING_DEPLOYMENT.md "Deploy contract".
#
#   scripts/staging/deploy.sh <phase> [args]      phase = migrate | start | rollback | logs
#
# Required env: STAGING_DEPLOY_METHOD (allowlisted: a committed hook scripts/staging/methods/<m>.sh),
# STAGING_SHA (40-hex), STAGING_IMAGE_ARCHIVE (docker save tarball of the image built for that SHA),
# STAGING_ENV_FILE (mode-600 file with the runtime variables; never printed).
# The hook must exit non-zero on any failure; this dispatcher never turns a failure into success.
set -euo pipefail

phase="${1:-}"; shift || true
case "$phase" in migrate|start|rollback|logs) ;; *)
  echo "usage: deploy.sh migrate|start|rollback|logs" >&2; exit 2;; esac

method="${STAGING_DEPLOY_METHOD:-}"
if [[ ! "$method" =~ ^[a-z0-9][a-z0-9-]{1,40}$ ]]; then
  echo "STAGING_TARGET_MISSING: STAGING_DEPLOY_METHOD is not set or not a valid name" >&2; exit 3
fi
hook="$(cd "$(dirname "$0")" && pwd)/methods/${method}.sh"
if [ ! -f "$hook" ]; then
  echo "STAGING_TARGET_MISSING: no hook for method '${method}' (implemented: $(ls "$(dirname "$hook")" 2>/dev/null | sed -n 's/\.sh$//p' | tr '\n' ' '))" >&2
  exit 3
fi
[[ "${STAGING_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo "STAGING_SHA must be a 40-hex commit" >&2; exit 2; }
if [ "$phase" = "migrate" ] || [ "$phase" = "start" ]; then
  [ -f "${STAGING_IMAGE_ARCHIVE:-}" ] || { echo "STAGING_IMAGE_ARCHIVE missing" >&2; exit 2; }
  [ -f "${STAGING_ENV_FILE:-}" ] || { echo "STAGING_ENV_FILE missing" >&2; exit 2; }
fi
exec bash "$hook" "$phase" "$@"
