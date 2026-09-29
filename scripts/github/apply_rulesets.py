"""Apply .github/rulesets/*.json to the repository (CR-STG-002). Idempotent.

    python scripts/github/apply_rulesets.py [--repo owner/name] [--dry-run]

Uses the GitHub CLI (``gh api``) with the caller's own login. Creates a ruleset when its
name is absent, updates it when present, and prints the differences it found. Rulesets
not described in the directory are reported, never deleted.
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
        check=True,
    )
    return json.loads(done.stdout) if done.stdout.strip() else None


def normalise(ruleset: dict) -> dict:
    return {k: ruleset.get(k) for k in COMPARE_KEYS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="thanhbn123/vip-viettelpost")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    wanted = {
        json.loads(p.read_text())["name"]: json.loads(p.read_text())
        for p in sorted(RULESETS_DIR.glob("*.json"))
    }
    existing = {r["name"]: r["id"] for r in gh(f"repos/{args.repo}/rulesets")}
    for name in sorted(set(existing) - set(wanted)):
        print(f"NOTE     ruleset '{name}' exists on GitHub but not in the repo (left as is)")
    for name, body in wanted.items():
        if name in existing:
            current = gh(f"repos/{args.repo}/rulesets/{existing[name]}")
            same = normalise(current) == normalise(body)
            print(f"{'SAME' if same else 'UPDATE':8} {name}")
            if not same and not args.dry_run:
                gh("-X", "PUT", f"repos/{args.repo}/rulesets/{existing[name]}", payload=body)
        else:
            print(f"CREATE   {name}")
            if not args.dry_run:
                gh("-X", "POST", f"repos/{args.repo}/rulesets", payload=body)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
