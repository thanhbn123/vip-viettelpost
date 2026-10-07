"""G13: PostgreSQL-specific verification (runs only when TEST_POSTGRES_URL is set; the CI
``postgres`` job always sets it). Complements the suite that already runs on both backends.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.models import Shipment, ShippingWebhookEvent
from app.db.session import make_engine, make_session_factory
from app.repositories.shipping import Actor, ActorType, NewShipment, ShippingRepository
from tests.conftest import POSTGRES_URL, _reset_postgres, alembic_config

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="needs TEST_POSTGRES_URL")
SYSTEM = Actor(ActorType.SYSTEM, "pg-test")


@pytest.fixture
def pg():
    _reset_postgres(POSTGRES_URL)
    command.upgrade(alembic_config(POSTGRES_URL), "head")
    engine = make_engine(POSTGRES_URL)
    yield engine, make_session_factory(engine)
    engine.dispose()


def provider_id(sessions):
    with sessions() as s:
        return ShippingRepository(s).get_provider_by_code("VIETTEL_POST").id


def test_column_types_are_postgres_native(pg):
    engine, _ = pg
    cols = {c["name"]: str(c["type"]) for c in inspect(engine).get_columns("shipments")}
    assert cols["cod_amount"] == "NUMERIC(18, 2)" and cols["actual_fee"] == "NUMERIC(18, 2)"
    assert "TIMESTAMP" in cols["created_at"]
    with engine.connect() as conn:
        tz = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='shipments' AND column_name='created_at'"
            )
        ).scalar()
        jsonb = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='shipping_webhook_events' AND column_name='payload_json'"
            )
        ).scalar()
    assert tz == "timestamp with time zone" and jsonb == "jsonb"


def test_numeric_precision_round_trip_at_the_limits(pg):
    _, sessions = pg
    pid = provider_id(sessions)
    values = [Decimal("0.01"), Decimal("9999999999999999.99"), Decimal("123456789.10")]
    with sessions() as s, s.begin():
        repo = ShippingRepository(s)
        ids = [
            repo.create_shipment(
                NewShipment(order_id=f"P-{i}", provider_id=pid, cod_amount=v), SYSTEM
            ).id
            for i, v in enumerate(values)
        ]
    with sessions() as s:
        stored = [s.get(Shipment, i).cod_amount for i in ids]
    assert stored == values and all(isinstance(v, Decimal) for v in stored)


def test_numeric_rejects_values_beyond_the_column(pg):
    from sqlalchemy.exc import DataError

    engine, _ = pg
    with pytest.raises(DataError):  # numeric field overflow
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO shipments (order_id, provider_id, status, package_count, "
                    "cod_amount, currency, created_at, updated_at) SELECT 'X', id, 'DRAFT', 0, "
                    "10000000000000000.00, 'VND', now(), now() FROM shipping_providers"
                )
            )


def test_jsonb_round_trip_keeps_unicode_and_nesting(pg):
    _, sessions = pg
    pid = provider_id(sessions)
    payload = {"RECEIVER_FULLNAME": "Nguyễn Thị Ánh", "POD": {"IMAGES": ["a", "b"]}, "N": 1}
    with sessions() as s, s.begin():
        row, _ = ShippingRepository(s).record_webhook_event(
            pid, fingerprint="c" * 64, payload=payload, tracking_number="T"
        )
        rid = row.id
    with sessions() as s:
        assert s.get(ShippingWebhookEvent, rid).payload_json == payload
    with sessions() as s:
        name = s.execute(
            text(
                "SELECT payload_json->>'RECEIVER_FULLNAME' FROM shipping_webhook_events WHERE id=:i"
            ),
            {"i": rid},
        ).scalar()
    assert name == "Nguyễn Thị Ánh"


def test_timestamptz_is_stored_in_utc_and_returned_aware(pg):
    _, sessions = pg
    pid = provider_id(sessions)
    ict = datetime(2026, 9, 29, 10, 0, tzinfo=timezone(timedelta(hours=7)))
    with sessions() as s, s.begin():
        sid = (
            ShippingRepository(s)
            .create_shipment(NewShipment(order_id="TZ", provider_id=pid), SYSTEM)
            .id
        )
        s.get(Shipment, sid).operation_lock_at = ict
    with sessions() as s:
        back = s.get(Shipment, sid).operation_lock_at
    assert back == ict and back.utcoffset() == timedelta(0) and back.tzinfo is not None
    assert back == datetime(2026, 9, 29, 3, 0, tzinfo=UTC)


def test_foreign_keys_restrict(pg):
    engine, sessions = pg
    pid = provider_id(sessions)
    with sessions() as s, s.begin():
        ShippingRepository(s).create_shipment(NewShipment(order_id="FK", provider_id=pid), SYSTEM)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM shipping_providers WHERE id=:p"), {"p": pid})


def test_duplicate_webhook_fingerprint_is_refused_by_the_database(pg):
    engine, sessions = pg
    pid = provider_id(sessions)
    insert = text(
        "INSERT INTO shipping_webhook_events (provider_id, fingerprint, payload_json, "
        "received_at, processing_status, attempt_count, requires_review) "
        "VALUES (:p, :f, '{}'::jsonb, now(), 'RECEIVED', 0, false)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"p": pid, "f": "d" * 64})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert, {"p": pid, "f": "d" * 64})


def test_check_constraints_are_enforced(pg):
    engine, _ = pg
    bad = [
        "INSERT INTO shipments (order_id, provider_id, status, package_count, cod_amount, "
        "currency, created_at, updated_at) SELECT 'C', id, 'SOMEWHERE', 0, 0, 'VND', now(), "
        "now() FROM shipping_providers",
        "INSERT INTO shipments (order_id, provider_id, status, package_count, cod_amount, "
        "currency, created_at, updated_at) SELECT 'C', id, 'DRAFT', 0, -1, 'VND', now(), "
        "now() FROM shipping_providers",
    ]
    for statement in bad:
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(statement))


def test_partial_unique_index_predicate_matches_the_model(pg):
    engine, _ = pg
    with engine.connect() as conn:
        definition = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname='uq_shipments_active_provider_order'"
            )
        ).scalar()
    assert "UNIQUE" in definition
    # PostgreSQL normalises "status NOT IN (...)" to "status <> ALL (ARRAY[...])".
    import re

    assert "<> ALL" in definition or "NOT IN" in definition.upper()
    excluded = set(re.findall(r"'([A-Z_]+)'", definition))
    assert excluded == {"DRAFT", "CANCELLED"}  # exactly the inactive statuses of D-022


def test_create_time_replay_savepoint_recovers_an_aborted_transaction(pg):
    """G09 verifier INFO-5: a replay failure after partial writes, with the PG transaction
    aborted, must roll back to the savepoint and still let the outer commit succeed."""
    _, sessions = pg
    pid = provider_id(sessions)
    with sessions() as s, s.begin():
        sid = (
            ShippingRepository(s)
            .create_shipment(NewShipment(order_id="SP", provider_id=pid), SYSTEM)
            .id
        )
        try:
            with s.begin_nested():
                s.get(Shipment, sid).provider_status = "partial-write"
                s.flush()
                s.execute(text("SELECT * FROM table_that_does_not_exist"))
        except Exception:
            pass
        s.get(Shipment, sid).tracking_number = "OUTER-COMMIT"
    with sessions() as s:
        row = s.get(Shipment, sid)
    assert row.tracking_number == "OUTER-COMMIT" and row.provider_status is None


def test_dump_toc_counter_matches_a_real_pg_dump(pg, tmp_path):
    """The deploy's table counter, run against output from a REAL pg_dump/pg_restore.

    The unit tests for the migrate phase drive a FAKE pg_restore, so they prove the
    dispatcher wiring and the ordering but say nothing about the real TOC format -- and
    that gap is exactly where the first version of this counter was wrong (it matched the
    "TABLE DATA" entry of every table and reported double). This test reads the awk program
    out of remote.sh, so it fails if the two drift apart, and runs it on a genuine archive.
    """
    import re
    import shutil
    import subprocess
    from pathlib import Path

    for tool in ("pg_dump", "pg_restore", "awk"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} is not on this runner")

    engine, _ = pg
    with engine.connect() as conn:
        expected = conn.execute(
            text(
                "select count(*) from pg_tables "
                "where schemaname not in ('pg_catalog', 'information_schema')"
            )
        ).scalar()
    assert expected > 1, "migrated database should have several tables"

    dsn = POSTGRES_URL.replace("postgresql+psycopg://", "postgresql://")
    dump = tmp_path / "pre-migration.dump"
    subprocess.run(["pg_dump", "-Fc", "--no-owner", "-f", str(dump), dsn], check=True, timeout=120)
    toc = subprocess.run(
        ["pg_restore", "--list"],
        stdin=dump.open("rb"),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    assert " TABLE DATA " in toc, "real TOC should contain the entries that fooled the counter"

    remote = (Path(__file__).resolve().parents[2] / "scripts/staging/vps/remote.sh").read_text()

    def awk(program: str) -> int:
        out = subprocess.run(
            ["awk", program], input=toc, capture_output=True, text=True, check=True, timeout=60
        )
        return int(out.stdout.strip())

    # The gate: entry count, which is what BACKUP_INCOMPLETE actually tests.
    gate = re.search(r"awk '(NF && \$0 !~ .*?)'", remote, re.S)
    assert gate, "could not find the TOC entry counter in remote.sh"
    assert awk(gate.group(1)) > expected  # tables, their data, constraints, indexes...

    # The operator-facing table count.
    counter = re.search(r"awk '(\$4 == \"TABLE\".*?)'", remote, re.S)
    assert counter, "could not find the TOC table counter in remote.sh"
    assert awk(counter.group(1)) == expected

    # And a truncated archive must be rejected, not silently counted as zero tables.
    broken = tmp_path / "broken.dump"
    broken.write_bytes(dump.read_bytes()[: max(64, dump.stat().st_size // 3)])
    rejected = subprocess.run(
        ["pg_restore", "--list"], stdin=broken.open("rb"), capture_output=True, timeout=60
    )
    assert rejected.returncode != 0
