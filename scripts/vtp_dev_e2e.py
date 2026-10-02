"""Viettel Post DEVELOPMENT end-to-end check (CR-SHP-001 G08). See docs/VTP_DEV_E2E.md.

Runs the real ``ViettelPostProvider`` against the Viettel Post **development** environment
only. Read-only by default (authenticate, services, fee). Creating a test order - which
creates state at Viettel Post - needs BOTH ``--create`` and ``VTP_E2E_ALLOW_CREATE=yes``;
the order is cancelled immediately afterwards.

    VTP_E2E_SCENARIO=scenario.json python -m scripts.vtp_dev_e2e [--create]

(Run as a module from the repository root so ``app`` is importable.)

Credentials come from the environment (VTP_TOKEN, or VTP_USERNAME + VTP_PASSWORD) and are
never printed. Evidence (no secrets, no personal data) is written as JSON.

Exit codes: 0 authenticate, services (non-empty) and fee all passed (and create/cancel when
requested) · 1 a step failed or was skipped · 2 refused (non-development URL, bad scenario
or settings) · 3 BLOCKED_EXTERNAL_CREDENTIAL (no credentials configured).
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.config import VTP_DEV_BASE_URL
from app.domain.models import Address, Money, ShipmentPackage
from app.providers.base.dto import CreateShipmentRequest, FeeRequest, ServiceQuery
from app.providers.viettel_post.auth import ViettelPostAuth
from app.providers.viettel_post.client import ViettelPostClient
from app.providers.viettel_post.provider import ViettelPostProvider

EXIT_OK, EXIT_FAIL, EXIT_REFUSED, EXIT_BLOCKED = 0, 1, 2, 3


@dataclass
class Step:
    name: str
    status: str  # PASS | FAIL | SKIPPED | NOT_SAFE
    duration_ms: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Report:
    base_url: str
    started_at: str
    steps: list[Step] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """FAIL anywhere, or a required read-only step not PASS (a skip is not success)."""
        required = {"authenticate", "get_services", "calculate_fee"}
        return any(s.status == "FAIL" for s in self.steps) or any(
            s.status != "PASS" for s in self.steps if s.name in required
        )


def load_scenario(path: str | None) -> dict[str, Any]:
    """Load and VALIDATE the scenario; errors name fields only, never input values."""
    if not path:
        raise ValueError("VTP_E2E_SCENARIO is not set (path to a scenario JSON)")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("scenario is not valid JSON") from exc
    for key in ("sender", "receiver", "packages", "provider_options"):
        if key not in data:
            raise ValueError(f"scenario is missing '{key}'")
    try:
        data["_parsed"] = {
            "sender": Address(**data["sender"]),
            "receiver": Address(**data["receiver"]),
            "packages": [ShipmentPackage(**p) for p in data["packages"]],
            "cod": Money(**data["cod_amount"]) if data.get("cod_amount") else None,
        }
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise ValueError(f"scenario has invalid fields: {fields}") from None
    except TypeError:
        raise ValueError("scenario has unexpected field names") from None
    return data


def auth_mode(env: dict[str, str]) -> str:
    """``static_token`` (not verified by any call) or ``login`` (Login + ownerconnect)."""
    return "static_token" if env.get("VTP_TOKEN") else "login"


def build_provider(env: dict[str, str], transport=None) -> ViettelPostProvider:
    base_url = env.get("VTP_BASE_URL") or VTP_DEV_BASE_URL
    client = ViettelPostClient(
        base_url=base_url,
        timeout=float(env.get("VTP_TIMEOUT_SECONDS") or 20.0),
        transport=transport,
    )
    auth = ViettelPostAuth(
        client,
        username=env.get("VTP_USERNAME") or "",
        password=env.get("VTP_PASSWORD") or "",
        static_token=env.get("VTP_TOKEN") or "",
    )
    return ViettelPostProvider(client, auth)


async def _timed(report: Report, name: str, coro_factory) -> Any:
    started = time.perf_counter()
    try:
        result, evidence = await coro_factory()
    except Exception as exc:  # recorded, never re-raised: the run reports every step
        report.steps.append(
            Step(
                name,
                "FAIL",
                round((time.perf_counter() - started) * 1000, 1),
                error=type(exc).__name__,
            )
        )
        return None
    report.steps.append(
        Step(name, "PASS", round((time.perf_counter() - started) * 1000, 1), evidence)
    )
    return result


async def run(
    env: dict[str, str], scenario: dict[str, Any], *, create: bool, transport=None
) -> Report:
    report = Report(
        base_url=env.get("VTP_BASE_URL") or VTP_DEV_BASE_URL,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    provider = build_provider(env, transport)
    parsed = scenario["_parsed"]
    sender, receiver, packages = parsed["sender"], parsed["receiver"], parsed["packages"]
    options = scenario["provider_options"]
    cod = parsed["cod"]
    try:

        async def auth():
            result = await provider.authenticate()
            # A static VTP_TOKEN is used as-is: no call is made, and partnerdev getPriceAll /
            # getPrice do not check the Token header (CR-STG-007: a fake token passed). Only
            # Login + ownerconnect, or a create + cancel, prove Viettel Post accepted it.
            return result, {"authenticated": result.authenticated, "auth_mode": auth_mode(env)}

        if await _timed(report, "authenticate", auth) is None:
            return report

        async def services():
            result = await provider.get_services(
                ServiceQuery(
                    sender=sender,
                    receiver=receiver,
                    packages=packages,
                    cod_amount=cod,
                    provider_options=options,
                )
            )
            return result, {
                "count": len(result),
                "service_codes": sorted({s.service_code for s in result}),
            }

        found = await _timed(report, "get_services", services)
        if found is not None and not found:
            report.steps[-1].status = "FAIL"
            report.steps[-1].error = "no services returned for this route"
        service_code = scenario.get("service_code") or (found[0].service_code if found else None)

        async def fee():
            result = await provider.calculate_fee(
                FeeRequest(
                    sender=sender,
                    receiver=receiver,
                    packages=packages,
                    service_code=service_code,
                    cod_amount=cod,
                    provider_options=options,
                )
            )
            return result, {
                "service_code": service_code,
                "total": str(result.total.amount),
                "currency": result.total.currency,
            }

        if service_code:
            await _timed(report, "calculate_fee", fee)
        else:
            report.steps.append(Step("calculate_fee", "SKIPPED", error="no service code"))

        if any(s.status != "PASS" for s in report.steps):
            report.steps.append(Step("create_shipment", "SKIPPED", error="earlier step not PASS"))
            report.steps.append(Step("cancel_shipment", "SKIPPED", error="nothing created"))
            return report

        allowed = env.get("VTP_E2E_ALLOW_CREATE") == "yes"
        if not (create and allowed):
            reason = "not requested (--create)" if not create else "VTP_E2E_ALLOW_CREATE!=yes"
            report.steps.append(Step("create_shipment", "NOT_SAFE", error=reason))
            report.steps.append(Step("cancel_shipment", "SKIPPED", error="nothing created"))
            return report

        order_id = scenario.get("order_id_prefix", "VIP-E2E-") + time.strftime("%Y%m%d%H%M%S")

        async def create_order():
            result = await provider.create_shipment(
                CreateShipmentRequest(
                    order_id=order_id,
                    sender=sender,
                    receiver=receiver,
                    packages=packages,
                    service_code=service_code,
                    cod_amount=cod,
                    provider_options=options,
                )
            )
            return result, {
                "order_id": order_id,
                "tracking_number": result.tracking_number,
                "status": result.status.value,
            }

        created = await _timed(report, "create_shipment", create_order)
        if created is None:
            report.steps.append(Step("cancel_shipment", "SKIPPED", error="create failed"))
            return report

        async def cancel():
            result = await provider.cancel_shipment(created.tracking_number)
            return result, {
                "tracking_number": result.tracking_number,
                "cancelled": result.cancelled,
            }

        await _timed(report, "cancel_shipment", cancel)
        return report
    finally:
        await provider.close()


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, transport=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--create",
        action="store_true",
        help="also create + cancel a test order (needs VTP_E2E_ALLOW_CREATE=yes)",
    )
    parser.add_argument("--evidence", default="vtp-dev-e2e-evidence.json")
    args = parser.parse_args(argv)
    env = dict(os.environ if env is None else env)

    base_url = (env.get("VTP_BASE_URL") or VTP_DEV_BASE_URL).rstrip("/")
    if base_url != VTP_DEV_BASE_URL:
        print(f"REFUSED: VTP_BASE_URL must be the development URL {VTP_DEV_BASE_URL}")
        return EXIT_REFUSED
    if not (env.get("VTP_TOKEN") or (env.get("VTP_USERNAME") and env.get("VTP_PASSWORD"))):
        print("BLOCKED_EXTERNAL_CREDENTIAL: set VTP_TOKEN or VTP_USERNAME + VTP_PASSWORD")
        return EXIT_BLOCKED
    try:
        float(env.get("VTP_TIMEOUT_SECONDS") or 20.0)
    except ValueError:
        print("REFUSED: VTP_TIMEOUT_SECONDS is not a number")
        return EXIT_REFUSED
    try:
        scenario = load_scenario(env.get("VTP_E2E_SCENARIO"))
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return EXIT_REFUSED

    report = asyncio.run(run(env, scenario, create=args.create, transport=transport))
    Path(args.evidence).write_text(
        json.dumps(
            {
                "base_url": report.base_url,
                "started_at": report.started_at,
                # Binds the evidence to the deployed commit; acceptance requires a match.
                "sha": env.get("VTP_E2E_SHA"),
                "auth_mode": auth_mode(env),
                "steps": [asdict(s) for s in report.steps],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for step in report.steps:
        detail = step.error or json.dumps(step.evidence, ensure_ascii=False)
        print(f"[{step.status}] {step.name} ({step.duration_ms} ms) {detail}")
    if auth_mode(env) == "static_token":
        print(
            "NOTE: VTP_TOKEN is used as-is and the read-only endpoints do not check it; "
            "the credential is NOT verified unless create + cancel PASS (CR-STG-007)."
        )
    return EXIT_FAIL if report.failed else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
