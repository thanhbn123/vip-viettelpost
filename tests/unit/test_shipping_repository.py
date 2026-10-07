"""Persistence tests for ShippingRepository on SQLite built by the real migration."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Shipment,
    ShipmentCod,
    ShipmentEvent,
    ShipmentPackage,
    ShippingAuditLog,
    ShippingWebhookEvent,
)
from app.db.session import make_engine, make_session_factory
from app.db.types import to_money
from app.repositories.redaction import REDACTED
from app.repositories.shipping import (
    Actor,
    ActorType,
    AddressRecord,
    AuditAction,
    NewPackage,
    NewShipment,
    NewShipmentEvent,
    ShippingRepository,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
USER = Actor(ActorType.USER, "user-1")
T0 = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


def fp(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def session(migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def repo(session):
    return ShippingRepository(session)


@pytest.fixture
def vtp(repo):
    # Seeded by migration shp_0002.
    provider = repo.get_provider_by_code("VIETTEL_POST")
    assert provider is not None
    return provider


@pytest.fixture
def ghn(repo):
    return repo.create_provider("GHN", "Giao Hang Nhanh")


def make_shipment(repo, provider, **overrides):
    data = {
        "order_id": "ORD-1",
        "provider_id": provider.id,
        "tracking_number": "VTP123",
        "packages": [NewPackage(weight_grams=500, length_cm=10, width_cm=10, height_cm=5)],
        "cod_amount": Decimal(150000),
        "receiver": AddressRecord(name="A", phone="0900000000", province="Ha Noi"),
    }
    data.update(overrides)
    return repo.create_shipment(NewShipment(**data), USER)


# -- providers / accounts -------------------------------------------------------


def test_provider_code_is_unique(repo, session, vtp):
    with pytest.raises(IntegrityError):
        repo.create_provider("VIETTEL_POST", "Duplicate")
    session.rollback()


def test_provider_code_must_be_uppercase(repo, session):
    with pytest.raises(IntegrityError):
        repo.create_provider("viettel_post", "lower")
    session.rollback()


def test_schema_accepts_any_provider_code(repo):
    for code in ("SUPERSHIP", "GHN", "GHTK", "VIPORDER_FLEET", "NEW_CARRIER"):
        assert repo.create_provider(code, code).id is not None


def test_account_stores_secret_reference_not_secret(repo, session, vtp):
    account = repo.create_account(
        vtp.id,
        "main",
        secret_reference="env://VTP_TOKEN",
        metadata={"region": "north", "api_token": "should-not-persist"},
    )
    assert account.secret_reference == "env://VTP_TOKEN"
    assert account.metadata_json == {"region": "north", "api_token": REDACTED}
    with pytest.raises(IntegrityError):
        repo.create_account(vtp.id, "raw", secret_reference="plain-value-no-scheme")
    session.rollback()


def test_shipment_account_must_belong_to_same_provider(repo, session, vtp, ghn):
    ghn_account = repo.create_account(ghn.id, "ghn-main")
    with pytest.raises(IntegrityError):
        make_shipment(repo, vtp, shipping_account_id=ghn_account.id)
    session.rollback()


# -- shipments -----------------------------------------------------------------


def test_create_and_get_shipment(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    session.commit()
    session.expunge_all()

    loaded = repo.get_shipment(shipment.id)
    assert loaded.order_id == "ORD-1"
    assert loaded.status == "DRAFT"
    assert loaded.package_count == 1
    assert loaded.receiver_province == "Ha Noi"
    assert loaded.cod_amount == Decimal("150000.00")
    assert loaded.created_at.tzinfo is not None
    assert repo.get_shipment_by_tracking(vtp.id, "VTP123").id == shipment.id
    assert repo.get_shipment_by_tracking(vtp.id, "missing") is None

    cod = session.scalar(select(ShipmentCod).where(ShipmentCod.shipment_id == shipment.id))
    assert cod.expected_amount == Decimal("150000.00") and cod.status == "PENDING"

    audit = session.scalars(select(ShippingAuditLog)).all()
    assert [a.action for a in audit] == ["SHIPMENT_CREATED"]
    assert audit[0].after_json["cod_amount"] == "150000.00"


def test_tracking_unique_per_provider(repo, session, vtp, ghn):
    make_shipment(repo, vtp)
    make_shipment(repo, ghn)  # same tracking, other provider: allowed
    session.commit()
    with pytest.raises(IntegrityError):
        make_shipment(repo, vtp, order_id="ORD-2")
    session.rollback()


def test_null_tracking_allows_many_drafts(repo, session, vtp):
    """NULLs are distinct in UNIQUE on both SQLite and PostgreSQL."""
    make_shipment(repo, vtp, tracking_number=None)
    make_shipment(repo, vtp, tracking_number=None, order_id="ORD-2")
    session.commit()
    assert session.scalar(select(func.count()).select_from(Shipment)) == 2


def test_invalid_status_rejected(repo, session, vtp):
    with pytest.raises(IntegrityError):
        make_shipment(repo, vtp, status="LOST_IN_SPACE")
    session.rollback()


# -- money -------------------------------------------------------------------------


def test_money_round_trips_exactly_at_max_precision(repo, session, vtp):
    big = Decimal("9999999999999999.99")  # 18 significant digits: float cannot hold this
    assert float(big) != big
    shipment = make_shipment(repo, vtp, cod_amount=big, estimated_fee=Decimal("0.01"))
    session.commit()
    session.expunge_all()
    loaded = repo.get_shipment(shipment.id)
    assert loaded.cod_amount == big
    assert loaded.estimated_fee == Decimal("0.01")
    assert isinstance(loaded.cod_amount, Decimal)


def test_money_rejects_float_and_extra_decimals():
    with pytest.raises(TypeError):
        to_money(1.5)
    with pytest.raises(ValueError):
        to_money(Decimal("1.005"))
    with pytest.raises(ValueError):
        to_money(Decimal(10000000000000000))
    assert to_money(15000) == Decimal("15000.00")
    assert to_money("12.30") == Decimal("12.30")


def test_negative_cod_rejected_by_database(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE shipments SET cod_amount = -1 WHERE id = :id"), {"id": shipment.id}
        )
    session.rollback()


# -- packages ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "package",
    [
        NewPackage(weight_grams=0),
        NewPackage(weight_grams=-5),
        NewPackage(weight_grams=100, length_cm=0),
        NewPackage(weight_grams=100, width_cm=-1),
        NewPackage(weight_grams=100, height_cm=0),
    ],
)
def test_package_constraints(repo, session, vtp, package):
    with pytest.raises(IntegrityError):
        make_shipment(repo, vtp, packages=[package])
    session.rollback()


def test_package_index_positive_and_unique(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(ShipmentPackage(shipment_id=shipment.id, package_index=0, weight_grams=1))
        session.flush()
    session.rollback()
    with pytest.raises(IntegrityError):
        session.add(ShipmentPackage(shipment_id=shipment.id, package_index=1, weight_grams=1))
        session.flush()
    session.rollback()


def test_packages_are_indexed_from_one(repo, vtp):
    shipment = make_shipment(
        repo, vtp, packages=[NewPackage(weight_grams=100), NewPackage(weight_grams=200)]
    )
    assert [p.package_index for p in shipment.packages] == [1, 2]
    assert shipment.package_count == 2


# -- events -----------------------------------------------------------------------------


def test_append_event_keeps_history(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    _, created1 = repo.append_shipment_event(
        shipment, NewShipmentEvent("CREATED", T0, provider_status="100", provider_event_id="e1")
    )
    _, created2 = repo.append_shipment_event(
        shipment,
        NewShipmentEvent("IN_TRANSIT", T0 + timedelta(hours=2), provider_event_id="e2"),
    )
    session.commit()
    assert created1 and created2
    history = repo.list_shipment_events(shipment.id)
    assert [e.canonical_status for e in history] == ["CREATED", "IN_TRANSIT"]
    assert history[0].occurred_at == T0


def test_duplicate_provider_event_id_is_idempotent(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    first, created = repo.append_shipment_event(
        shipment, NewShipmentEvent("PICKED", T0, provider_event_id="dup")
    )
    again, created_again = repo.append_shipment_event(
        shipment, NewShipmentEvent("PICKED", T0, provider_event_id="dup")
    )
    session.commit()
    assert created and not created_again and again.id == first.id
    assert session.scalar(select(func.count()).select_from(ShipmentEvent)) == 1


def test_events_without_provider_event_id_are_all_kept(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    repo.append_shipment_event(shipment, NewShipmentEvent("PICKED", T0))
    repo.append_shipment_event(shipment, NewShipmentEvent("PICKED", T0))
    session.commit()
    assert len(repo.list_shipment_events(shipment.id)) == 2


def test_event_provider_must_match_shipment_provider(repo, session, vtp, ghn):
    shipment = make_shipment(repo, vtp)
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(
            ShipmentEvent(
                shipment_id=shipment.id,
                provider_id=ghn.id,
                canonical_status="PICKED",
                occurred_at=T0,
            )
        )
        session.flush()
    session.rollback()


def test_naive_datetime_rejected(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    with pytest.raises(Exception, match="timezone-aware"):
        naive = datetime(2026, 1, 1)  # noqa: DTZ001 - deliberately naive
        repo.append_shipment_event(shipment, NewShipmentEvent("PICKED", naive))
    session.rollback()


# -- webhooks ---------------------------------------------------------------------------


def test_webhook_duplicate_handled_by_repository(repo, session, vtp):
    payload = {"DATA": {"ORDER_NUMBER": "VTP123", "ORDER_STATUS": 200}, "TOKEN": "leak-me"}
    row, created = repo.record_webhook_event(
        vtp.id,
        fingerprint=fp("body-1"),
        payload=payload,
        tracking_number="VTP123",
        headers={"Content-Type": "application/json", "Authorization": "Bearer x", "X-Token": "y"},
    )
    again, created_again = repo.record_webhook_event(
        vtp.id, fingerprint=fp("body-1"), payload=payload
    )
    session.commit()
    assert created and not created_again and again.id == row.id
    assert session.scalar(select(func.count()).select_from(ShippingWebhookEvent)) == 1
    assert row.payload_json["TOKEN"] == REDACTED
    assert row.payload_json["DATA"]["ORDER_NUMBER"] == "VTP123"
    assert row.headers_json == {"content-type": "application/json"}
    assert row.processing_status == "RECEIVED"


def test_webhook_duplicate_by_event_id(repo, session, vtp):
    repo.record_webhook_event(vtp.id, fingerprint=fp("a"), payload={}, event_id="evt-1")
    _, created = repo.record_webhook_event(
        vtp.id, fingerprint=fp("b"), payload={}, event_id="evt-1"
    )
    assert not created
    assert repo.find_webhook_event(vtp.id, fingerprint=fp("zzz")) is None


def test_webhook_fingerprint_unique_per_provider_in_database(session, vtp, ghn):
    session.add(ShippingWebhookEvent(provider_id=vtp.id, fingerprint=fp("x"), payload_json={}))
    session.add(ShippingWebhookEvent(provider_id=ghn.id, fingerprint=fp("x"), payload_json={}))
    session.flush()  # same fingerprint across providers is fine
    with pytest.raises(IntegrityError):
        session.add(ShippingWebhookEvent(provider_id=vtp.id, fingerprint=fp("x"), payload_json={}))
        session.flush()
    session.rollback()


def test_webhook_event_id_unique_but_nullable(session, vtp):
    session.add(ShippingWebhookEvent(provider_id=vtp.id, fingerprint=fp("1"), payload_json={}))
    session.add(ShippingWebhookEvent(provider_id=vtp.id, fingerprint=fp("2"), payload_json={}))
    session.add(
        ShippingWebhookEvent(provider_id=vtp.id, fingerprint=fp("3"), payload_json={}, event_id="e")
    )
    session.flush()
    with pytest.raises(IntegrityError):
        session.add(
            ShippingWebhookEvent(
                provider_id=vtp.id, fingerprint=fp("4"), payload_json={}, event_id="e"
            )
        )
        session.flush()
    session.rollback()


def test_webhook_fingerprint_must_be_sha256_length(session, vtp):
    with pytest.raises(IntegrityError):
        session.add(ShippingWebhookEvent(provider_id=vtp.id, fingerprint="short", payload_json={}))
        session.flush()
    session.rollback()


def test_mark_webhook_processed(repo, session, vtp):
    row, _ = repo.record_webhook_event(vtp.id, fingerprint=fp("p"), payload={})
    repo.mark_webhook_event(row, "FAILED", error_code="SHIPMENT_NOT_FOUND")
    repo.mark_webhook_event(row, "PROCESSED", processed_at=T0)
    session.commit()
    assert row.attempt_count == 2 and row.error_code is None and row.processed_at == T0


# -- audit ------------------------------------------------------------------------------


def test_audit_log_insert_redacts_secrets(repo, session):
    log = repo.write_audit_log(
        entity_type="shipping_account",
        entity_id="7",
        action=AuditAction.ACCOUNT_CHANGED,
        actor=Actor(ActorType.SYSTEM),
        before={"password": "old", "enabled": True},
        after={"password": "new", "enabled": False, "nested": [{"privateKey": "k"}]},
        reason="rotate",
    )
    session.commit()
    assert log.id is not None
    assert log.before_json == {"password": REDACTED, "enabled": True}
    assert log.after_json["nested"] == [{"privateKey": REDACTED}]


def test_audit_actor_type_checked(repo, session):
    with pytest.raises(IntegrityError):
        session.add(
            ShippingAuditLog(entity_type="x", entity_id="1", action="A", actor_type="ROBOT")
        )
        session.flush()
    session.rollback()


# -- foreign keys / delete strategy ------------------------------------------------------


def test_cannot_delete_provider_with_shipments(repo, session, vtp):
    make_shipment(repo, vtp)
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM shipping_providers WHERE id = :id"), {"id": vtp.id})
    session.rollback()


def test_cannot_delete_shipment_with_history(repo, session, vtp):
    shipment = make_shipment(repo, vtp, cod_amount=Decimal(0))
    repo.append_shipment_event(shipment, NewShipmentEvent("CREATED", T0))
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM shipments WHERE id = :id"), {"id": shipment.id})
    session.rollback()


def test_cannot_delete_shipment_with_cod(repo, session, vtp):
    shipment = make_shipment(repo, vtp)  # COD > 0 creates shipment_cod row
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM shipments WHERE id = :id"), {"id": shipment.id})
    session.rollback()


def test_deleting_bare_draft_cascades_packages_only(repo, session, vtp):
    shipment = make_shipment(repo, vtp, cod_amount=Decimal(0))
    session.commit()
    session.execute(text("DELETE FROM shipments WHERE id = :id"), {"id": shipment.id})
    session.commit()
    assert session.scalar(select(func.count()).select_from(ShipmentPackage)) == 0
    # the audit trail outlives the shipment (no FK)
    assert session.scalar(select(func.count()).select_from(ShippingAuditLog)) == 1


def test_deleting_webhook_keeps_event_and_nulls_reference(repo, session, vtp):
    shipment = make_shipment(repo, vtp)
    hook, _ = repo.record_webhook_event(vtp.id, fingerprint=fp("w"), payload={})
    event, _ = repo.append_shipment_event(
        shipment, NewShipmentEvent("PICKED", T0, webhook_event_id=hook.id)
    )
    session.commit()
    session.execute(text("DELETE FROM shipping_webhook_events WHERE id = :id"), {"id": hook.id})
    session.commit()
    session.expire_all()
    assert session.get(ShipmentEvent, event.id).webhook_event_id is None


def test_foreign_keys_enforced_on_sqlite(session):
    if session.get_bind().dialect.name != "sqlite":
        pytest.skip("SQLite PRAGMA check; PostgreSQL always enforces foreign keys")
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
