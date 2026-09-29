"""Staging acceptance runner (CR-STG-001): checks + evidence + verdict.

    python -m scripts.staging.acceptance --base-url https://<staging> --kind staging \\
        --expected-sha <40-hex> --evidence acceptance.json \\
        [--logs-cmd "scripts/staging/deploy.sh logs"] [--vtp-evidence vtp.json]

Secrets come from the environment and are never printed: ACCEPT_API_KEY (raw key for one
API_KEYS entry) and ACCEPT_WEBHOOK_SECRET (= WEBHOOK_SHARED_SECRET). Values listed in
ACCEPT_SCAN_VARS (comma-separated env names) are searched for in every response body and
in the log excerpt; only the variable NAME is reported on a hit.

Verdict rules (docs/STAGING_ACCEPTANCE.md):
* ``--kind staging``: G15 = PASS only if every G15 check is PASS on the real staging URL;
  G08 = PASS only if the Viettel Post DEVELOPMENT evidence shows authenticate, services
  and fee PASS (no evidence -> BLOCKED). A check that could not run is NOT a pass.
* ``--kind rehearsal`` (CI, ephemeral containers): never ACCEPTED; G15 = NOT_STAGING.

Side effect on the target: the idempotency check stores ONE synthetic webhook event for a
tracking number ``ACCEPT-<sha8>-<epoch>`` that matches no shipment (row IGNORED).
"""

import argparse
import json
import os
import re
import secrets as _random
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import unquote

import httpx

from scripts.smoke_test import run_checks

WEBHOOK = "/api/v1/shipping/webhooks/viettel-post"
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")
G15_CHECKS = (
    "health",
    "readiness",
    "deployed_sha",
    "migration_head",
    "smoke",
    "webhook_reachable",
    "webhook_malformed_rejected",
    "webhook_idempotency",
    "no_secret_in_responses",
    "log_redaction",
)


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | NOT_RUN
    detail: str = ""


@dataclass
class Evidence:
    kind: str
    base_url: str
    expected_sha: str
    started_at: str
    checks: list[Check] = field(default_factory=list)
    g15: str = "FAIL"
    g08: str = "BLOCKED_EXTERNAL_CREDENTIAL"
    verdict: str = "NOT_ACCEPTED"


def secret_values(env: dict[str, str]) -> dict[str, list[str]]:
    """name -> sensitive substrings (whole value; for URLs also the password part)."""
    out: dict[str, list[str]] = {}
    for name in [n.strip() for n in env.get("ACCEPT_SCAN_VARS", "").split(",") if n.strip()]:
        value = env.get(name, "")
        parts = [value] if len(value) >= 8 else []
        # URL with user and password: capture the password part. Pattern split so the
        # repo's secret tripwire does not mistake this regex for a credential-bearing URL.
        match = re.match(r"^[a-z0-9+]+:" + r"//[^:/@]+:([^@]+)@", value)
        if match and len(match.group(1)) >= 6:
            parts.append(match.group(1))
            decoded = unquote(match.group(1))
            if decoded != match.group(1):
                parts.append(decoded)
        if parts:
            out[name] = parts
    return out


def leaked(text: str, secrets: dict[str, list[str]]) -> list[str]:
    return sorted(name for name, parts in secrets.items() if any(p in text for p in parts))


def run(
    client: httpx.Client,
    env: dict[str, str],
    *,
    kind: str,
    expected_sha: str,
    logs: "str | None | Callable[[], str | None]",
    vtp_evidence: dict | None,
) -> Evidence:
    """``logs`` may be a callable: it is called AFTER the HTTP checks, so the scanned log
    excerpt covers the requests this run made."""
    ev = Evidence(
        kind=kind,
        base_url=str(client.base_url),
        expected_sha=expected_sha,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    bodies: list[str] = []
    secrets = secret_values(env)
    # Every request of this run carries this id; the log excerpt must contain it to prove the
    # logs come from the instance that served this run (M1, verifier PR #28).
    marker = f"accept-{expected_sha[:8]}-{int(time.time())}-{_random.token_hex(8)}"
    client.headers["X-Request-ID"] = marker

    def capture(response: httpx.Response) -> None:  # every response, smoke included (M2)
        response.read()
        bodies.append(response.text)

    client.event_hooks.setdefault("response", []).append(capture)
    api_key = env.get("ACCEPT_API_KEY", "")
    hook_secret = env.get("ACCEPT_WEBHOOK_SECRET", "")

    def add(name, ok, detail=""):
        ev.checks.append(Check(name, "PASS" if ok else "FAIL", detail))

    get, post = client.get, client.post

    try:
        r = get("/health")
        add("health", r.status_code == 200, str(r.status_code))
        r = get("/health/ready")
        ready = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        failing = [k for k, v in (ready.get("checks") or {}).items() if not v.get("ok")]
        add("readiness", r.status_code == 200 and not failing, f"{r.status_code} failing={failing}")
        version = ready.get("version")
        add("deployed_sha", version == expected_sha, f"running={version}")
        mig = (ready.get("checks") or {}).get("migrations", {})
        add("migration_head", bool(mig.get("ok")), f"current={mig.get('current')}")
    except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        for name in ("health", "readiness", "deployed_sha", "migration_head"):
            if name not in {c.name for c in ev.checks}:
                add(name, False, type(exc).__name__)

    if api_key:
        smoke = run_checks(client, api_key)
        failed = [s.name for s in smoke if not s.ok]
        add("smoke", not failed, f"{len(smoke) - len(failed)}/{len(smoke)} failed={failed}")
    else:
        ev.checks.append(Check("smoke", "NOT_RUN", "ACCEPT_API_KEY not provided"))

    try:
        wrong = {"DATA": {"ORDER_NUMBER": "ACCEPT-PROBE", "ORDER_STATUS": 200}, "TOKEN": "wrong"}
        r = post(WEBHOOK, json=wrong)
        add("webhook_reachable", r.status_code == 401, f"wrong TOKEN -> {r.status_code}")
        r = post(WEBHOOK, content=b"{not json", headers={"content-type": "application/json"})
        add("webhook_malformed_rejected", r.status_code == 400, str(r.status_code))
        if hook_secret:
            tracking = f"ACCEPT-{expected_sha[:8]}-{int(time.time())}"
            event = {
                "DATA": {
                    "ORDER_NUMBER": tracking,
                    "ORDER_STATUS": 200,
                    "ORDER_STATUSDATE": time.strftime("%d/%m/%Y %H:%M:%S"),
                },
                "TOKEN": hook_secret,
            }
            first = post(WEBHOOK, json=event)
            second = post(WEBHOOK, json=event)
            results = (
                first.status_code,
                first.json().get("result"),
                second.status_code,
                second.json().get("result"),
            )
            add(
                "webhook_idempotency",
                results == (200, "ACCEPTED", 200, "DUPLICATE"),
                f"{results} tracking={tracking}",
            )
        else:
            ev.checks.append(
                Check("webhook_idempotency", "NOT_RUN", "ACCEPT_WEBHOOK_SECRET not provided")
            )
    except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        for name in ("webhook_reachable", "webhook_malformed_rejected", "webhook_idempotency"):
            if name not in {c.name for c in ev.checks}:
                add(name, False, type(exc).__name__)

    client.event_hooks["response"].remove(capture)
    hits = leaked("\n".join(bodies), secrets)
    add(
        "no_secret_in_responses",
        not hits and not any(JWT.search(b) for b in bodies),
        f"variables found: {hits}" if hits else f"{len(bodies)} responses scanned",
    )

    if callable(logs):
        logs = logs()
    if logs is None or not logs.strip():
        ev.checks.append(Check("log_redaction", "NOT_RUN", "no log excerpt provided"))
    elif marker not in logs:
        ev.checks.append(
            Check("log_redaction", "NOT_RUN", "log excerpt does not contain this run's request id")
        )
    else:
        hits = leaked(logs, secrets)
        jwt = bool(JWT.search(logs))
        add(
            "log_redaction",
            not hits and not jwt,
            f"variables found: {hits}, jwt={jwt}"
            if hits or jwt
            else f"{len(logs.splitlines())} log lines scanned",
        )

    if vtp_evidence is None:
        ev.g08 = "BLOCKED_EXTERNAL_CREDENTIAL"
    else:
        try:
            steps = {s["name"]: s["status"] for s in vtp_evidence.get("steps", [])}
            required = ("authenticate", "get_services", "calculate_fee")
            base = str(vtp_evidence.get("base_url", "")).rstrip("/")
            same_sha = vtp_evidence.get("sha") == expected_sha  # evidence of THIS run (M3)
            ok = (
                base == "https://partnerdev.viettelpost.vn"
                and same_sha
                and all(steps.get(n) == "PASS" for n in required)
            )
            ev.g08 = "PASS" if ok else "FAIL"
        except (AttributeError, TypeError, KeyError):
            ev.g08 = "FAIL"

    statuses = {c.name: c.status for c in ev.checks}
    g15_ok = all(statuses.get(n) == "PASS" for n in G15_CHECKS)
    if kind == "staging":
        ev.g15 = "PASS" if g15_ok else "FAIL"
        ev.verdict = "ACCEPTED" if g15_ok else "NOT_ACCEPTED"
    else:
        ev.g15 = "NOT_STAGING"
        ev.g08 = "NOT_STAGING"  # rehearsal never reports a gate result (L3)
        ev.verdict = "REHEARSAL_PASS" if g15_ok else "REHEARSAL_FAIL"
    return ev


def main(
    argv: list[str] | None = None,
    env: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="staging acceptance")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--kind", choices=("staging", "rehearsal"), required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--logs", help="log excerpt file (read before the checks)")
    parser.add_argument("--logs-cmd", help="shell command printing the app log, run AFTER checks")
    parser.add_argument("--vtp-evidence")
    args = parser.parse_args(argv)
    env = dict(os.environ if env is None else env)
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        print("--expected-sha must be a 40-hex commit")
        return 2
    if args.kind == "staging" and not args.base_url.startswith("https://"):
        print("staging acceptance requires an https:// base URL")
        return 2

    def fetch_logs() -> str | None:
        if args.logs_cmd:
            done = subprocess.run(
                args.logs_cmd, shell=True, capture_output=True, text=True, timeout=120
            )
            return (done.stdout + done.stderr) if done.returncode == 0 else None
        return Path(args.logs).read_text(errors="replace") if args.logs else None

    try:
        vtp = json.loads(Path(args.vtp_evidence).read_text()) if args.vtp_evidence else None
    except (OSError, ValueError):
        vtp = {"malformed": True}
    if args.kind == "staging" and "@" in args.base_url.split("//", 1)[-1].split("/", 1)[0]:
        print("staging base URL must not contain user info")
        return 2
    with httpx.Client(base_url=args.base_url, timeout=15.0, transport=transport) as client:
        ev = run(
            client,
            env,
            kind=args.kind,
            expected_sha=args.expected_sha,
            logs=fetch_logs,
            vtp_evidence=vtp,
        )
    Path(args.evidence).write_text(
        json.dumps({**asdict(ev), "checks": [asdict(c) for c in ev.checks]}, indent=2),
        encoding="utf-8",
    )
    for c in ev.checks:
        print(f"[{c.status}] {c.name} {c.detail}")
    print(f"KIND={ev.kind} G15={ev.g15} G08={ev.g08} VERDICT={ev.verdict}")
    return 0 if ev.verdict in ("ACCEPTED", "REHEARSAL_PASS") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
