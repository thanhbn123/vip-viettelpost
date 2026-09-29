"""Migration tests for shp_0001 on a throwaway SQLite file.

Schema is created ONLY through Alembic here, never through create_all.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.db import models
from app.db.base import Base
from app.db.session import make_engine
from app.domain.models.shipment import ShipmentStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_REVISION = "shp_0001_shipping_gateway"
HEAD = "shp_0002_webhook_processing"
TABLES = {
    "shipping_providers",
    "shipping_accounts",
    "shipments",
    "shipment_packages",
    "shipment_events",
    "shipment_fees",
    "shipment_cod",
    "shipment_reconciliation",
    "shipping_webhook_events",
    "shipping_audit_logs",
}


def alembic_config(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "migrations" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def test_single_head_is_latest_revision():
    script = ScriptDirectory.from_config(alembic_config("sqlite://"))
    assert script.get_heads() == [HEAD]


def test_upgrade_creates_all_tables(db_url):
    command.upgrade(alembic_config(db_url), "head")
    engine = make_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert TABLES <= tables
    with engine.connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == HEAD


def test_downgrade_removes_all_tables_and_reupgrade_works(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = make_engine(db_url)
    assert not (TABLES & set(inspect(engine).get_table_names()))
    command.upgrade(cfg, "head")
    assert TABLES <= set(inspect(engine).get_table_names())


def test_migration_matches_orm_metadata(db_url):
    """No autogenerate diff between migration and models.

    Scope: Alembic compare_metadata covers tables, columns, types, nullability,
    indexes, unique constraints and FKs. It does NOT compare CHECK constraints;
    those are covered by test_check_constraints_match_orm below.
    """
    command.upgrade(alembic_config(db_url), "head")
    engine = make_engine(db_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def test_check_constraints_match_orm(db_url):
    command.upgrade(alembic_config(db_url), "head")
    insp = inspect(make_engine(db_url))
    for table in Base.metadata.sorted_tables:
        expected = {c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}
        actual = {c["name"] for c in insp.get_check_constraints(table.name)}
        assert actual == expected, table.name


def test_status_check_lists_every_domain_status():
    """Adding a ShipmentStatus requires a migration; this test catches forgetting it."""
    assert set(models.SHIPMENT_STATUSES) == {s.value for s in ShipmentStatus}
    source = (REPO_ROOT / "migrations" / "versions" / f"{BASE_REVISION}.py").read_text()
    for status in ShipmentStatus:
        assert f"'{status.value}'" in source


def test_constraint_names_fit_postgres_limit():
    for table in Base.metadata.sorted_tables:
        names = [c.name for c in table.constraints] + [i.name for i in table.indexes]
        for name in names:
            assert name and len(name) <= 63, (table.name, name)


def test_application_code_never_creates_schema():
    offenders = []
    for path in (REPO_ROOT / "app").rglob("*.py"):
        text = path.read_text()
        if "create_all(" in text or "CREATE TABLE" in text or "ALTER TABLE" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_money_columns_are_never_float(db_url):
    command.upgrade(alembic_config(db_url), "head")
    sqlite = db_url.startswith("sqlite")
    insp = inspect(make_engine(db_url))
    money = {
        ("shipments", "cod_amount"),
        ("shipments", "estimated_fee"),
        ("shipments", "actual_fee"),
        ("shipment_fees", "amount"),
        ("shipment_cod", "expected_amount"),
        ("shipment_cod", "collected_amount"),
        ("shipment_cod", "remitted_amount"),
        ("shipment_reconciliation", "expected_amount"),
        ("shipment_reconciliation", "actual_amount"),
        ("shipment_reconciliation", "difference_amount"),
        ("shipment_packages", "declared_value"),
    }
    for table, column in money:
        col = next(c for c in insp.get_columns(table) if c["name"] == column)
        type_name = str(col["type"]).upper()
        assert "FLOAT" not in type_name and "REAL" not in type_name and "DOUBLE" not in type_name
        if sqlite:
            assert type_name == "BIGINT", (table, column, type_name)  # minor units
        else:
            assert type_name == "NUMERIC(18, 2)", (table, column, type_name)


# --- shp_0002 (G05) ------------------------------------------------------------------


def test_shp_0002_seeds_viettel_post(db_url):
    command.upgrade(alembic_config(db_url), "head")
    engine = make_engine(db_url)
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT code, enabled FROM shipping_providers ORDER BY code"
        ).all()
    assert [tuple(r) for r in rows] == [("VIETTEL_POST", True)]


def test_shp_0002_downgrade_to_0001_and_back(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, BASE_REVISION)
    engine = make_engine(db_url)
    columns = {c["name"] for c in inspect(engine).get_columns("shipment_events")}
    assert "requires_review" not in columns
    nullable = {c["name"]: c["nullable"] for c in inspect(engine).get_columns("shipment_events")}
    assert nullable["canonical_status"] is False and nullable["occurred_at"] is False
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == HEAD


def test_shp_0002_downgrade_refuses_to_lose_review_events(db_url):
    from datetime import UTC, datetime

    from app.db.session import make_session_factory
    from app.repositories.shipping import (
        Actor,
        ActorType,
        NewShipment,
        NewShipmentEvent,
        ShippingRepository,
    )

    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = make_engine(db_url)
    with make_session_factory(engine)() as session, session.begin():
        repo = ShippingRepository(session)
        provider = repo.get_provider_by_code("VIETTEL_POST")
        shipment = repo.create_shipment(
            NewShipment(order_id="O", provider_id=provider.id, tracking_number="T"),
            Actor(ActorType.SYSTEM),
        )
        repo.append_shipment_event(
            shipment,
            NewShipmentEvent(
                None,
                None,
                provider_status="999",
                requires_review=True,
                received_at=datetime(2026, 9, 29, tzinfo=UTC),
            ),
        )
    engine.dispose()
    with pytest.raises(RuntimeError, match="refused"):
        command.downgrade(cfg, BASE_REVISION)
    engine = make_engine(db_url)
    with engine.connect() as conn:
        assert MigrationContext.configure(conn).get_current_revision() == HEAD
        assert conn.exec_driver_sql("SELECT count(*) FROM shipment_events").scalar() == 1


def test_shp_0002_check_rejects_null_status_without_review(db_url):
    from sqlalchemy.exc import IntegrityError

    command.upgrade(alembic_config(db_url), "head")
    engine = make_engine(db_url)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO shipments (order_id, provider_id, tracking_number, status, "
                "package_count, cod_amount, currency, created_at, updated_at) "
                "SELECT 'O', id, 'T', 'CREATED', 0, 0, 'VND', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP FROM shipping_providers"
            )
            conn.exec_driver_sql(
                "INSERT INTO shipment_events (shipment_id, provider_id, canonical_status, "
                "requires_review, received_at) SELECT id, provider_id, NULL, false, "
                "CURRENT_TIMESTAMP FROM shipments"
            )


def test_shp_0002_webhook_status_check_lists_every_domain_status():
    source = (REPO_ROOT / "migrations" / "versions" / f"{HEAD}.py").read_text()
    for status in ShipmentStatus:
        assert f"'{status.value}'" in source
