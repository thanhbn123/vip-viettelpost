"""Liveness, readiness and metrics (G11). Readiness never calls the carrier."""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.auth import parse_api_keys, require_api_key
from app.core.config import settings
from app.core.database import get_engine
from app.core.metrics import metrics

router = APIRouter()
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@lru_cache(maxsize=1)
def expected_head() -> str:
    cfg = Config(str(MIGRATIONS / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return ScriptDirectory.from_config(cfg).get_current_head()


def readiness_checks(engine=None) -> dict[str, dict]:
    checks: dict[str, dict] = {}
    try:
        head = expected_head()
    except Exception as exc:  # broken/multi-head migration tree: not ready, not a 500
        head = None
        checks["migration_scripts"] = {"ok": False, "error": type(exc).__name__}
    try:
        with (engine or get_engine()).connect() as conn:
            conn.execute(text("SELECT 1"))
            checks["database"] = {"ok": True}
            try:
                current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception as exc:  # reachable but never migrated
                current = None
                checks["migrations"] = {"ok": False, "expected": head, "error": type(exc).__name__}
            else:
                checks["migrations"] = {"ok": current == head, "current": current, "expected": head}
    except Exception as exc:  # report, do not raise: readiness must answer
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        checks["migrations"] = {"ok": False, "expected": head}
    checks["webhook_secret"] = {"ok": bool(settings.webhook_shared_secret)}
    # Without API keys every protected route answers 503: not ready (verifier PR #22 L4).
    checks["api_keys"] = {"ok": bool(parse_api_keys(settings.api_keys))}
    checks["provider_credentials"] = {
        "ok": bool(settings.vtp_token or (settings.vtp_username and settings.vtp_password))
    }
    return checks


@router.get("/health")
def health():
    """Liveness: the process answers."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready():
    checks = readiness_checks()
    ok = all(c["ok"] for c in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ready" if ok else "not_ready",
            "checks": checks,
            # Deployment evidence: which commit is actually running (public repo, not secret).
            "version": settings.app_git_sha,
        },
    )


def replay_backlog(sessions=None) -> dict:
    """Events that should have been attached to a shipment by the replay job but were not.

    This is the only thing that makes a replay job that is NOT running visible: the job
    itself is silent when nobody schedules it, and the events simply sit in the table
    (docs/RUNBOOK_REPLAY_WEBHOOKS.md). A value above zero that stays up means the job is
    not running, or is failing.

    Never raises: a metrics endpoint that 500s because of a slow query takes the rest of
    the metrics with it, and losing the counters is worse than losing this one gauge.
    """
    from app.jobs.replay_webhooks import unmatched_with_shipment

    try:
        if sessions is None:
            from app.core.database import get_session_factory

            sessions = get_session_factory()
        return {
            "name": "webhook_events_unmatched_with_shipment",
            "value": unmatched_with_shipment(sessions),
        }
    except Exception as exc:
        return {"name": "webhook_events_unmatched_with_shipment", "error": type(exc).__name__}


@router.get("/metrics", dependencies=[Depends(require_api_key)])
def metrics_snapshot():
    return {**metrics.snapshot(), "gauges": [replay_backlog()]}
