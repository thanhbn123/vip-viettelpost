"""Shared database fixtures.

Every DB test runs on a throwaway SQLite file. When ``TEST_POSTGRES_URL`` is set
(CI PostgreSQL service container, or a local throwaway cluster) the same tests also run
on PostgreSQL: the ``public`` schema of that database is dropped and recreated before
each test, so the URL must point at a DISPOSABLE database. Never point it at shared,
staging or production data.
"""

import os
import tempfile
from pathlib import Path

# Before any application import: tests must never open the default ./vip_shipping.db or
# a DATABASE_URL inherited from the developer's shell or .env (env var beats .env).
_TEST_DB_DIR = tempfile.mkdtemp(prefix="vip-shipping-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TEST_DB_DIR) / 'default.db'}"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001 - pytest hook signature
    import shutil

    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
BACKENDS = ["sqlite"] + (["postgresql"] if POSTGRES_URL else [])


def alembic_config(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "migrations" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def _reset_postgres(url: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


@pytest.fixture(params=BACKENDS)
def db_url(request, tmp_path: Path) -> str:
    """URL of an EMPTY database (no schema yet)."""
    if request.param == "postgresql":
        _reset_postgres(POSTGRES_URL)
        return POSTGRES_URL
    return f"sqlite:///{tmp_path / 'shipping.db'}"


@pytest.fixture
def migrated_url(db_url: str) -> str:
    """URL of a database upgraded to the Alembic head."""
    command.upgrade(alembic_config(db_url), "head")
    return db_url


@pytest.fixture(autouse=True)
def _authenticated_api(request):
    """Most API tests are about behaviour, not auth: stand in an authenticated caller.

    ``tests/integration/test_auth.py`` opts out (marker ``real_auth``) and exercises the
    real ``require_api_key`` dependency.
    """
    from app.api.auth import require_api_key
    from app.main import app

    if request.node.get_closest_marker("real_auth"):
        app.dependency_overrides.pop(require_api_key, None)
        yield
        return

    from fastapi import Request

    async def fake(request: Request) -> str:
        request.state.api_key_id = "tests"
        return "tests"

    app.dependency_overrides[require_api_key] = fake
    yield
    app.dependency_overrides.pop(require_api_key, None)
