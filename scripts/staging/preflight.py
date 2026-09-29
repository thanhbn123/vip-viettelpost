"""Staging preflight: are the required secrets/variables PRESENT? (CR-STG-001)

Never reads secret values. The workflow passes one boolean per secret, computed by
GitHub itself (``HAS_<NAME>: ${{ secrets.<NAME> != '' }}``); non-secret variables are
passed as values and validated (HTTPS URL, allowlisted deploy method, scenario JSON).

    python -m scripts.staging.preflight --gate g15|g08|all --report preflight.json

Exit 0 = everything for the gate is present and valid; 1 = something is missing or
invalid (names are listed; values are never printed).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

METHODS_DIR = Path(__file__).resolve().parent / "methods"
METHOD_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
DEV_VTP_URL = "https://partnerdev.viettelpost.vn"

G15_SECRETS = ("DATABASE_URL", "WEBHOOK_SHARED_SECRET", "API_KEYS", "SMOKE_API_KEY")
VTP_CREDENTIALS = (("VTP_TOKEN",), ("VTP_USERNAME", "VTP_PASSWORD"))
OPTIONAL_SECRETS = ("DATABASE_URL_PSQL",)


def implemented_methods() -> list[str]:
    """The allowlist: a method exists only if its hook script is committed."""
    return sorted(p.stem for p in METHODS_DIR.glob("*.sh") if METHOD_NAME.match(p.stem))


def _has(env: dict[str, str], name: str) -> bool:
    return env.get(f"HAS_{name}", "").strip().lower() == "true"


def check(env: dict[str, str], gate: str) -> dict:
    missing: list[str] = []
    invalid: list[str] = []

    def need_secret(name: str) -> None:
        if not _has(env, name):
            missing.append(f"secret {name}")

    if gate in ("g15", "all"):
        for name in G15_SECRETS:
            need_secret(name)
        base = env.get("STAGING_BASE_URL", "").strip()
        if not base:
            missing.append("variable STAGING_BASE_URL")
        elif not base.startswith("https://"):
            invalid.append("variable STAGING_BASE_URL (must start with https://)")
        method = env.get("STAGING_DEPLOY_METHOD", "").strip()
        if not method:
            missing.append("variable STAGING_DEPLOY_METHOD")
        elif method not in implemented_methods():
            invalid.append(
                "variable STAGING_DEPLOY_METHOD (not an implemented method; "
                f"allowed: {implemented_methods() or 'none yet'})"
            )

    if gate in ("g08", "all"):
        if not any(all(_has(env, n) for n in group) for group in VTP_CREDENTIALS):
            missing.append("secret VTP_TOKEN or secrets VTP_USERNAME + VTP_PASSWORD")
        scenario = env.get("VTP_E2E_SCENARIO_JSON", "").strip()
        if not scenario:
            missing.append("variable VTP_E2E_SCENARIO_JSON")
        else:
            try:
                data = json.loads(scenario)
                if not isinstance(data, dict):
                    raise ValueError
            except ValueError:
                invalid.append("variable VTP_E2E_SCENARIO_JSON (not a JSON object)")
        vtp_url = env.get("VTP_BASE_URL", "").strip().rstrip("/")
        if vtp_url and vtp_url != DEV_VTP_URL:
            invalid.append("variable VTP_BASE_URL (must be the Viettel Post development URL)")

    optional_missing = [f"secret {n}" for n in OPTIONAL_SECRETS if not _has(env, n)]
    return {
        "gate": gate,
        "ok": not missing and not invalid,
        "missing": missing,
        "invalid": invalid,
        "optional_missing": optional_missing,
        "implemented_deploy_methods": implemented_methods(),
    }


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="staging preflight (presence only)")
    parser.add_argument("--gate", choices=("g15", "g08", "all"), default="all")
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    result = check(dict(os.environ if env is None else env), args.gate)
    if args.report:
        Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")
    for item in result["missing"]:
        print(f"MISSING  {item}")
    for item in result["invalid"]:
        print(f"INVALID  {item}")
    for item in result["optional_missing"]:
        print(f"optional {item} (not set)")
    if not result["ok"]:
        blocker = "STAGING_TARGET_MISSING" if args.gate != "g08" else "BLOCKED_EXTERNAL_CREDENTIAL"
        print(f"PREFLIGHT FAIL ({blocker}) — gate {args.gate}")
        return 1
    print(f"PREFLIGHT OK — gate {args.gate}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
