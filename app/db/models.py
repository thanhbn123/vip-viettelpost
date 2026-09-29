"""ORM models for the VIP Shipping Gateway persistence layer.

These are DB records, not domain models. Mapping to/from ``app.domain`` is
done by the service layer (see docs/DATABASE_SCHEMA.md, "Integration notes").

Schema is created ONLY by Alembic (``migrations/versions/``). Never use
metadata-based schema creation from application code.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import BigIntPK, JSONType, MoneyType, UTCDateTime, utcnow
from app.domain.models.shipment import ShipmentStatus

SHIPMENT_STATUSES: tuple[str, ...] = tuple(s.value for s in ShipmentStatus)

FEE_SOURCES = ("ESTIMATE", "PROVIDER_ACTUAL", "ADJUSTMENT")
COD_STATUSES = ("PENDING", "COLLECTED", "REMITTED", "PARTIAL", "FAILED", "CANCELLED")
RECONCILIATION_KINDS = ("COD", "FEE")
RECONCILIATION_STATUSES = ("PENDING", "MATCHED", "MISMATCH", "RESOLVED")
WEBHOOK_PROCESSING_STATUSES = (
    "RECEIVED",
    "PROCESSING",
    "PROCESSED",
    "FAILED",
    "IGNORED",
)
ACTOR_TYPES = ("USER", "SYSTEM", "PROVIDER", "WEBHOOK")


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def _created_at() -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), nullable=False, default=utcnow, server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class ShippingProvider(Base):
    __tablename__ = "shipping_providers"
    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint("code <> '' AND code = upper(code)", name="code_upper"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ShippingAccount(Base):
    """One credentialed account at a provider. Holds a secret REFERENCE only."""

    __tablename__ = "shipping_accounts"
    __table_args__ = (
        UniqueConstraint("provider_id", "account_name"),
        # Target of the composite FK from shipments (account must belong to provider).
        UniqueConstraint("id", "provider_id"),
        CheckConstraint("account_name <> ''", name="account_name_not_empty"),
        CheckConstraint(
            "secret_reference IS NULL OR secret_reference LIKE '%://%'",
            name="secret_reference_uri",
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("shipping_providers.id", ondelete="RESTRICT"), nullable=False
    )
    account_name: Mapped[str] = mapped_column(String(128), nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(String(128))
    secret_reference: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    provider: Mapped[ShippingProvider] = relationship()


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("provider_id", "tracking_number"),
        # Target of composite FKs from events / reconciliation.
        UniqueConstraint("id", "provider_id"),
        ForeignKeyConstraint(
            ["shipping_account_id", "provider_id"],
            ["shipping_accounts.id", "shipping_accounts.provider_id"],
            ondelete="RESTRICT",
        ),
        Index(None, "order_id"),
        Index(None, "status"),
        # shp_0003: one active shipment per (provider, order); DRAFT/CANCELLED excluded.
        Index(
            "uq_shipments_active_provider_order",
            "provider_id",
            "order_id",
            unique=True,
            postgresql_where=text("status NOT IN ('DRAFT', 'CANCELLED')"),
            sqlite_where=text("status NOT IN ('DRAFT', 'CANCELLED')"),
        ),
        CheckConstraint("order_id <> ''", name="order_id_not_empty"),
        CheckConstraint(_in("status", SHIPMENT_STATUSES), name="status_valid"),
        CheckConstraint("package_count >= 0", name="package_count_non_negative"),
        CheckConstraint("cod_amount >= 0", name="cod_amount_non_negative"),
        CheckConstraint(
            "estimated_fee IS NULL OR estimated_fee >= 0", name="estimated_fee_non_negative"
        ),
        CheckConstraint("actual_fee IS NULL OR actual_fee >= 0", name="actual_fee_non_negative"),
        CheckConstraint("length(currency) = 3", name="currency_iso"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("shipping_providers.id", ondelete="RESTRICT"), nullable=False
    )
    shipping_account_id: Mapped[int | None] = mapped_column(BigIntPK)
    tracking_number: Mapped[str | None] = mapped_column(String(64))
    service_code: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DRAFT", server_default=text("'DRAFT'")
    )
    provider_status: Mapped[str | None] = mapped_column(String(64))

    sender_name: Mapped[str | None] = mapped_column(String(255))
    sender_phone: Mapped[str | None] = mapped_column(String(32))
    sender_address_line: Mapped[str | None] = mapped_column(String(500))
    sender_ward: Mapped[str | None] = mapped_column(String(128))
    sender_district: Mapped[str | None] = mapped_column(String(128))
    sender_province: Mapped[str | None] = mapped_column(String(128))

    receiver_name: Mapped[str | None] = mapped_column(String(255))
    receiver_phone: Mapped[str | None] = mapped_column(String(32))
    receiver_address_line: Mapped[str | None] = mapped_column(String(500))
    receiver_ward: Mapped[str | None] = mapped_column(String(128))
    receiver_district: Mapped[str | None] = mapped_column(String(128))
    receiver_province: Mapped[str | None] = mapped_column(String(128))

    package_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    cod_amount: Mapped[Decimal] = mapped_column(
        MoneyType(), nullable=False, default=Decimal("0.00"), server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="VND", server_default=text("'VND'")
    )
    estimated_fee: Mapped[Decimal | None] = mapped_column(MoneyType())
    actual_fee: Mapped[Decimal | None] = mapped_column(MoneyType())

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    created_by: Mapped[str | None] = mapped_column(String(128))
    # shp_0003: in-flight provider mutation claim (e.g. "CANCEL"), see D-028.
    operation_lock: Mapped[str | None] = mapped_column(String(32))
    operation_lock_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    provider: Mapped[ShippingProvider] = relationship()
    packages: Mapped[list["ShipmentPackage"]] = relationship(
        back_populates="shipment",
        order_by="ShipmentPackage.package_index",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class ShipmentPackage(Base):
    __tablename__ = "shipment_packages"
    __table_args__ = (
        UniqueConstraint("shipment_id", "package_index"),
        CheckConstraint("package_index >= 1", name="package_index_positive"),
        CheckConstraint("weight_grams > 0", name="weight_positive"),
        CheckConstraint("length_cm IS NULL OR length_cm > 0", name="length_positive"),
        CheckConstraint("width_cm IS NULL OR width_cm > 0", name="width_positive"),
        CheckConstraint("height_cm IS NULL OR height_cm > 0", name="height_positive"),
        CheckConstraint(
            "declared_value IS NULL OR declared_value >= 0", name="declared_value_non_negative"
        ),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    package_index: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    length_cm: Mapped[int | None] = mapped_column(Integer)
    width_cm: Mapped[int | None] = mapped_column(Integer)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(500))
    declared_value: Mapped[Decimal | None] = mapped_column(MoneyType())
    created_at: Mapped[datetime] = _created_at()

    shipment: Mapped[Shipment] = relationship(back_populates="packages")


class ShippingWebhookEvent(Base):
    """Raw inbound webhook, stored before processing for idempotency and replay."""

    __tablename__ = "shipping_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider_id", "fingerprint"),
        UniqueConstraint("provider_id", "event_id"),
        Index(None, "tracking_number"),
        Index(None, "processing_status", "received_at"),
        CheckConstraint("length(fingerprint) = 64", name="fingerprint_sha256"),
        CheckConstraint(
            _in("processing_status", WEBHOOK_PROCESSING_STATUSES), name="processing_status_valid"
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint(_in("canonical_status", SHIPMENT_STATUSES), name="canonical_status_valid"),
        Index(None, "shipment_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("shipping_providers.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[str | None] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    tracking_number: Mapped[str | None] = mapped_column(String(64))
    order_id: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[Any] = mapped_column(JSONType, nullable=False)
    headers_json: Mapped[dict[str, str] | None] = mapped_column(JSONType)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="RECEIVED", server_default=text("'RECEIVED'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    # shp_0002: normalized result of processing, for review queues and replay.
    provider_status: Mapped[str | None] = mapped_column(String(64))
    provider_status_name: Mapped[str | None] = mapped_column(String(128))
    canonical_status: Mapped[str | None] = mapped_column(String(32))
    requires_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    fingerprint_basis: Mapped[str | None] = mapped_column(String(64))
    occurred_at_raw: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL")
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ShipmentEvent(Base):
    """Append-only normalized status history. Rows are never updated."""

    __tablename__ = "shipment_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shipment_id", "provider_id"],
            ["shipments.id", "shipments.provider_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("provider_id", "provider_event_id"),
        Index(None, "shipment_id", "occurred_at"),
        CheckConstraint(_in("canonical_status", SHIPMENT_STATUSES), name="canonical_status_valid"),
        CheckConstraint("canonical_status IS NOT NULL OR requires_review", name="status_or_review"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    provider_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    # NULL = provider status unknown or without unambiguous canonical (requires_review).
    canonical_status: Mapped[str | None] = mapped_column(String(32))
    requires_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    provider_status_name: Mapped[str | None] = mapped_column(String(128))
    provider_status: Mapped[str | None] = mapped_column(String(64))
    provider_event_id: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(255))
    # NULL when the provider time has no timezone and none is configured (raw kept).
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    occurred_at_raw: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, server_default=func.now()
    )
    webhook_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipping_webhook_events.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType)


class ShipmentFee(Base):
    """Itemised fee lines (estimate, provider actual, adjustment)."""

    __tablename__ = "shipment_fees"
    __table_args__ = (
        Index(None, "shipment_id"),
        CheckConstraint("fee_type <> ''", name="fee_type_not_empty"),
        CheckConstraint(_in("source", FEE_SOURCES), name="source_valid"),
        CheckConstraint("amount >= 0 OR source = 'ADJUSTMENT'", name="amount_non_negative"),
        CheckConstraint("length(currency) = 3", name="currency_iso"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    fee_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="VND", server_default=text("'VND'")
    )
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created_at()
    created_by: Mapped[str | None] = mapped_column(String(128))


class ShipmentCod(Base):
    """COD lifecycle for one shipment: expected -> collected by carrier -> remitted."""

    __tablename__ = "shipment_cod"
    __table_args__ = (
        UniqueConstraint("shipment_id"),
        CheckConstraint("expected_amount >= 0", name="expected_non_negative"),
        CheckConstraint(
            "collected_amount IS NULL OR collected_amount >= 0", name="collected_non_negative"
        ),
        CheckConstraint(
            "remitted_amount IS NULL OR remitted_amount >= 0", name="remitted_non_negative"
        ),
        CheckConstraint(_in("status", COD_STATUSES), name="status_valid"),
        CheckConstraint("length(currency) = 3", name="currency_iso"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="RESTRICT"), nullable=False
    )
    expected_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    collected_amount: Mapped[Decimal | None] = mapped_column(MoneyType())
    remitted_amount: Mapped[Decimal | None] = mapped_column(MoneyType())
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="VND", server_default=text("'VND'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    remitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    remittance_reference: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ShipmentReconciliation(Base):
    """One comparison of expected vs actual (COD or fee) against a provider statement."""

    __tablename__ = "shipment_reconciliation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shipment_id", "provider_id"],
            ["shipments.id", "shipments.provider_id"],
            ondelete="RESTRICT",
        ),
        Index(None, "shipment_id"),
        Index(None, "provider_id", "statement_reference"),
        CheckConstraint(_in("kind", RECONCILIATION_KINDS), name="kind_valid"),
        CheckConstraint(_in("status", RECONCILIATION_STATUSES), name="status_valid"),
        CheckConstraint(
            "difference_amount = actual_amount - expected_amount", name="difference_consistent"
        ),
        CheckConstraint("length(currency) = 3", name="currency_iso"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    provider_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    statement_reference: Mapped[str | None] = mapped_column(String(128))
    expected_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    actual_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    difference_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="VND", server_default=text("'VND'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    created_by: Mapped[str | None] = mapped_column(String(128))


class ShippingAuditLog(Base):
    """Append-only audit trail. Polymorphic (no FK) so it outlives the entity."""

    __tablename__ = "shipping_audit_logs"
    __table_args__ = (
        Index(None, "entity_type", "entity_id", "created_at"),
        CheckConstraint("entity_type <> ''", name="entity_type_not_empty"),
        CheckConstraint("action <> ''", name="action_not_empty"),
        CheckConstraint(_in("actor_type", ACTOR_TYPES), name="actor_type_valid"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    before_json: Mapped[Any | None] = mapped_column(JSONType)
    after_json: Mapped[Any | None] = mapped_column(JSONType)
    reason: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created_at()
