"""Liveness, readiness and metrics (G11). Readiness never calls the carrier."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_engine
from app.core.metrics import metrics

router = APIRouter()
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def expected_head() -> str:
    cfg = Config(str(MIGRATIONS / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return ScriptDirectory.from_config(cfg).get_current_head()


def readiness_checks(engine=None) -> dict[str, dict]:
    checks: dict[str, dict] = {}
    try:
        with (engine or get_engine()).connect() as conn:
            conn.execute(text("SELECT 1"))
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        head = expected_head()
        checks["database"] = {"ok": True}
        checks["migrations"] = {"ok": current == head, "current": current, "expected": head}
    except Exception as exc:  # report, do not raise: readiness must answer
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        checks["migrations"] = {"ok": False}
    checks["webhook_secret"] = {"ok": bool(settings.webhook_shared_secret)}
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
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )


@router.get("/metrics")
def metrics_snapshot():
    return metrics.snapshot()
