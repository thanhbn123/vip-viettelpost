"""Apply .github/rulesets/*.json to the repository (CR-STG-002). Idempotent.

    python scripts/github/apply_rulesets.py [--repo owner/name] [--dry-run]

Uses the GitHub CLI (``gh api``) with the caller's own login. Creates a ruleset when its
name is absent, updates it when it differs, prints which declared fields differ, and exits
non-zero on any API error (printing GitHub's message). Rulesets not described in the
directory are reported, never deleted. Drift is judged only on the fields declared in the
JSON: fields GitHub adds with default values (e.g. ``do_not_enforce_on_create``,
``allowed_merge_methods``) do not count as drift.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

RULESETS_DIR = Path(__file__).resolve().parents[2] / ".github" / "rulesets"
COMPARE_KEYS = ("target", "enforcement", "conditions", "bypass_actors", "rules")


def gh(*args: str, payload: dict | None = None) -> object:
    cmd = ["gh", "api", *args]
    if payload is not None:
        cmd += ["--input", "-"]
    done = subprocess.run(
        cmd,
        input=json.dumps(payload) if payload else None,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        print(f"gh api {' '.join(args)} failed: {done.stderr.strip()}", file=sys.stderr)
        raise SystemExit(done.returncode)
    return json.loads(done.stdout) if done.stdout.strip() else None


def _key(item: object) -> str:
    return json.dumps(item, sort_keys=True)


def declared_diff(wanted: object, current: object, path: str = "") -> list[str]:
    """Paths where ``current`` differs from ``wanted``, judged only on what ``wanted``
    declares (extra server-side fields are ignored)."""
    if isinstance(wanted, dict):
        if not isinstance(current, dict):
            return [path or "/"]
        out: list[str] = []
        for key, value in wanted.items():
            out += declared_diff(value, current.get(key), f"{path}/{key}")
        return out
    if (
        isinstance(wanted, list)
        and wanted
        and all(isinstance(x, dict) and "type" in x for x in wanted)
    ):
        # Rules: matched by type, order-insensitive; a missing or extra rule type is drift.
        by_type = {r.get("type"): r for r in current or [] if isinstance(r, dict)}
        out = [f"{path} (rule types)"] if set(by_type) != {r["type"] for r in wanted} else []
        for rule in wanted:
            out += declared_diff(rule, by_type.get(rule["type"]), f"{path}/{rule['type']}")
        return out
    if isinstance(wanted, list):
        if not isinstance(current, list) or len(wanted) != len(current):
            return [path]
        pairs = zip(sorted(wanted, key=_key), sorted(current, key=_key), strict=True)
        return [p for i, (w, c) in enumerate(pairs) for p in declared_diff(w, c, f"{path}[{i}]")]
    return [] if wanted == current else [path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="thanhbn123/vip-viettelpost")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    wanted = {
        json.loads(p.read_text())["name"]: json.loads(p.read_text())
        for p in sorted(RULESETS_DIR.glob("*.json"))
    }
    existing = {
        r["name"]: r["id"]
        for r in gh("--paginate", f"repos/{args.repo}/rulesets?per_page=100") or []
    }
    for name in sorted(set(existing) - set(wanted)):
        print(f"NOTE     ruleset '{name}' exists on GitHub but not in the repo (left as is)")
    for name, body in wanted.items():
        if name in existing:
            current = gh(f"repos/{args.repo}/rulesets/{existing[name]}")
            diffs = declared_diff({k: body[k] for k in COMPARE_KEYS if k in body}, current)
            print(f"{'UPDATE' if diffs else 'SAME':8} {name}" + (f"  {diffs}" if diffs else ""))
            if diffs and not args.dry_run:
                gh("-X", "PUT", f"repos/{args.repo}/rulesets/{existing[name]}", payload=body)
        else:
            print(f"CREATE   {name}")
            if not args.dry_run:
                gh("-X", "POST", f"repos/{args.repo}/rulesets", payload=body)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
