"""Shared database fixtures.

Every DB test runs on a throwaway SQLite file. When ``TEST_POSTGRES_URL`` is set
(CI PostgreSQL service container, or a local throwaway cluster) the same tests also run
on PostgreSQL: the ``public`` schema of that database is dropped and recreated before
each test, so the URL must point at a DISPOSABLE database. Never point it at shared,
staging or production data.
"""

import os
from pathlib import Path

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
