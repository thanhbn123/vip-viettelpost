"""Alembic environment for the VIP Shipping Gateway.

The database URL must be given explicitly, in this order of precedence:
  1. ``-x db_url=...`` on the alembic command line
  2. ``sqlalchemy.url`` set programmatically on the Config (tests)
  3. the ``DATABASE_URL`` environment variable
There is no fallback to app settings, so a migration can never hit a database
by accident.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = (
        context.get_x_argument(as_dictionary=True).get("db_url")
        or config.get_main_option("sqlalchemy.url")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        raise RuntimeError("No database URL. Pass -x db_url=... or set DATABASE_URL explicitly.")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        _run_with_connection(connectable)
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool, hide_parameters=True
    )
    with engine.connect() as connection:
        _run_with_connection(connection)


def _run_with_connection(connection) -> None:
    sqlite = connection.dialect.name == "sqlite"
    if sqlite:
        if connection.in_transaction():
            # PRAGMA foreign_keys is a no-op inside a transaction, and committing here
            # would commit the caller's own transaction. Refuse instead of doing either.
            raise RuntimeError("SQLite migrations need a connection without an open transaction")
        # SQLite batch migrations rebuild tables (copy + DROP + rename). With foreign keys
        # enforced, dropping a rebuilt PARENT table fires ON DELETE actions on its
        # children (e.g. SET NULL) and silently loses links. Follow SQLite's documented
        # ALTER procedure: FKs off during the migration, foreign_key_check around it.
        # Existing violations are refused BEFORE anything changes: Alembic's SQLite DDL
        # is not transactional here, so a check afterwards could only report, not undo.
        existing = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if existing:
            connection.rollback()
            raise RuntimeError(
                f"foreign key violations exist before migrating; fix them first: {existing[:5]}"
            )
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        # The PRAGMA auto-began a transaction that this function started; end it so
        # Alembic's own begin_transaction() owns (and commits) the migration transaction.
        connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=sqlite,
        compare_type=True,
    )
    try:
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if violations:
                    # The schema change itself introduced them. Reported loudly; on
                    # SQLite the DDL may already be applied (see the pre-check above).
                    raise RuntimeError(f"foreign key violations after migration: {violations[:5]}")
    finally:
        if sqlite:
            if connection.in_transaction():
                connection.rollback()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            if connection.in_transaction():
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
