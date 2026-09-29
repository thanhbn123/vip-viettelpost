"""Staging smoke test for the VIP Shipping Gateway (CR-SHP-001 G14).

Read-only by default: it never creates, cancels or changes anything and never calls
Viettel Post. It checks what a deployment must get right before real traffic.

    SMOKE_BASE_URL=https://staging.example.internal SMOKE_API_KEY=... \\
        python scripts/smoke_test.py

Exit code 0 = all checks passed; 1 = at least one failed. The API key is read from the
environment and never printed.
"""

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx

REQUIRED_HEADERS = ("X-Request-ID", "X-Content-Type-Options", "Cache-Control")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def run_checks(client: httpx.Client, api_key: str) -> list[Check]:
    results: list[Check] = []

    def check(name: str, fn: Callable[[], tuple[bool, str]]) -> None:
        try:
            ok, detail = fn()
        except Exception as exc:  # a smoke test reports, it does not crash
            ok, detail = False, f"{type(exc).__name__}"
        results.append(Check(name, ok, detail))

    key = {"X-API-Key": api_key}

    def health():
        r = client.get("/health")
        return r.status_code == 200 and r.json() == {"status": "ok"}, str(r.status_code)

    def ready():
        r = client.get("/health/ready")
        body = r.json()
        failing = [k for k, v in body.get("checks", {}).items() if not v.get("ok")]
        return r.status_code == 200, f"{r.status_code} failing={failing}"

    def headers():
        r = client.get("/health")
        missing = [h for h in REQUIRED_HEADERS if h not in r.headers]
        return not missing, f"missing={missing}"

    def auth_required():
        r = client.get("/api/v1/shipping/providers")
        return r.status_code == 401, str(r.status_code)

    def auth_accepted():
        r = client.get("/api/v1/shipping/providers", headers=key)
        enabled = [p["code"] for p in r.json() if p.get("enabled")] if r.status_code == 200 else []
        return r.status_code == 200 and "VIETTEL_POST" in enabled, f"{r.status_code} {enabled}"

    def listing():
        r = client.get("/api/v1/shipping/shipments", params={"limit": 1}, headers=key)
        return r.status_code == 200 and "total" in r.json(), str(r.status_code)

    def metrics():
        r = client.get("/metrics", headers=key)
        return r.status_code == 200 and "counters" in r.json(), str(r.status_code)

    def webhook_rejects_bad_token():
        body = {"DATA": {"ORDER_NUMBER": "SMOKE-NOPE", "ORDER_STATUS": 200}, "TOKEN": "wrong"}
        r = client.post("/api/v1/shipping/webhooks/viettel-post", json=body)
        return r.status_code == 401, str(r.status_code)

    def no_server_banner_leak():
        r = client.get("/api/v1/shipping/shipments/0", headers=key)
        text = r.text.lower()
        return "traceback" not in text and "sqlalchemy" not in text, str(r.status_code)

    for name, fn in [
        ("liveness /health", health),
        ("readiness /health/ready", ready),
        ("security headers", headers),
        ("API refuses missing key", auth_required),
        ("API accepts key; VIETTEL_POST enabled", auth_accepted),
        ("shipment listing", listing),
        ("metrics behind key", metrics),
        ("webhook refuses wrong TOKEN (no side effect)", webhook_rejects_bad_token),
        ("errors do not leak internals", no_server_banner_leak),
    ]:
        check(name, fn)
    return results


def main() -> int:  # pragma: no cover - thin CLI wrapper
    base_url = os.environ.get("SMOKE_BASE_URL")
    api_key = os.environ.get("SMOKE_API_KEY")
    if not base_url or not api_key:
        print("set SMOKE_BASE_URL and SMOKE_API_KEY", file=sys.stderr)
        return 2
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        results = run_checks(client, api_key)
    for r in results:
        print(f"[{'PASS' if r.ok else 'FAIL'}] {r.name} ({r.detail})")
    failed = [r for r in results if not r.ok]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
