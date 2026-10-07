#!/usr/bin/env bash
# Run the stored-webhook replay job against the release that is currently live on this
# host. Meant to be driven by a systemd timer (docs/RUNBOOK_REPLAY_WEBHOOKS.md).
#
# This lives in a file on purpose. The first version of it was written inline in an
# ExecStart= line, where systemd expands $sha itself before bash ever sees it: the
# variable came out empty, the --env-file path became "/srv/vip-staging/env/.env" and the
# image tag "vip-shipping-gateway:staging-", and the unit would have failed on its first
# fire. A script can be read, shellchecked and tested; an ExecStart one-liner cannot.
#
# Exit codes: 0 replayed, nothing left pending. 3 ran, but events are still unattached
# (that is the condition a person has to look at). Anything else: the run itself failed.
set -euo pipefail

dir="${STAGING_APP_DIR:-/srv/vip-staging}"
network="${STAGING_DOCKER_NETWORK:-vip-staging}"
image_repo="${STAGING_IMAGE_REPO:-vip-shipping-gateway}"

die() { echo "$*" >&2; exit 1; }

[ -f "$dir/STAGING_TARGET" ] || die "REPLAY_GUARD: $dir/STAGING_TARGET is missing — refusing to run outside the staging host"

sha_file="$dir/state/current_sha"
[ -r "$sha_file" ] || die "no release recorded: $sha_file is missing"
sha="$(tr -d '[:space:]' < "$sha_file")"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "current_sha is not a commit sha: '${sha:-empty}'"

envf="$dir/env/$sha.env"
[ -r "$envf" ] || die "env file for the live release is missing: $envf"
grep -q '^APP_ENV=staging$' "$envf" || die "STAGING_GUARD: $envf does not declare APP_ENV=staging"

exec docker run --rm --network "$network" --env-file "$envf" \
  "$image_repo:staging-$sha" python -m app.jobs.replay_webhooks
