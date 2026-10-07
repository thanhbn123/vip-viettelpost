# Deploy method hooks

A deploy method exists **only** when its hook `<method>.sh` is committed here (the allowlist
for `STAGING_DEPLOY_METHOD`). Contract: `docs/STAGING_DEPLOYMENT.md` → "Deploy contract".

| Method | Hook | Status |
|---|---|---|
| `vps` | `vps.sh` (+ remote part `../vps/remote.sh`, which is **not** a method) | DESIGNED/TESTED (fake transport); not yet verified on a real VPS — `docs/STAGING_DEPLOYMENT.md` → "Method `vps`" |

Only method hooks may live in this directory: every `*.sh` here becomes an allowed method.
