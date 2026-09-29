"""shp_0001: VIP Shipping Gateway persistence schema (CR-SHP-001).

Creates the 10 shipping tables. Self-contained on purpose: it does NOT import
application code, so later model changes cannot silently rewrite history.

Portability:
  * ids      BIGINT on PostgreSQL, INTEGER on SQLite (needed for autoincrement)
  * money    NUMERIC(18,2) on PostgreSQL, BIGINT minor units (x100) on SQLite;
             the ORM type app.db.types.MoneyType reads/writes both
  * JSON     JSONB on PostgreSQL, JSON (TEXT) on SQLite
  * time     TIMESTAMP WITH TIME ZONE (SQLite stores naive UTC)

Downgrade drops all 10 tables (data loss): only for dev/test or an
immediately-failed first deploy. See docs/DATABASE_SCHEMA.md.

Revision ID: shp_0001_shipping_gateway
Revises:
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "shp_0001_shipping_gateway"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen type definitions for this revision (see module docstring).
BIGINT_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
MONEY = sa.Numeric(18, 2).with_variant(sa.BigInteger(), "sqlite")
JSON_DOC = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "shipping_audit_logs",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("before_json", JSON_DOC, nullable=True),
        sa.Column("after_json", JSON_DOC, nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("action <> ''", name=op.f("ck_shipping_audit_logs_action_not_empty")),
        sa.CheckConstraint(
            "actor_type IN ('USER', 'SYSTEM', 'PROVIDER', 'WEBHOOK')",
            name=op.f("ck_shipping_audit_logs_actor_type_valid"),
        ),
        sa.CheckConstraint(
            "entity_type <> ''", name=op.f("ck_shipping_audit_logs_entity_type_not_empty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_audit_logs")),
    )
    op.create_index(
        op.f("ix_shipping_audit_logs_entity_type_entity_id_created_at"),
        "shipping_audit_logs",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "shipping_providers",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "code <> '' AND code = upper(code)", name=op.f("ck_shipping_providers_code_upper")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_providers")),
        sa.UniqueConstraint("code", name=op.f("uq_shipping_providers_code")),
    )
    op.create_table(
        "shipping_accounts",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("provider_id", BIGINT_ID, nullable=False),
        sa.Column("account_name", sa.String(length=128), nullable=False),
        sa.Column("external_account_id", sa.String(length=128), nullable=True),
        sa.Column("secret_reference", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("metadata_json", JSON_DOC, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "account_name <> ''", name=op.f("ck_shipping_accounts_account_name_not_empty")
        ),
        sa.CheckConstraint(
            "secret_reference IS NULL OR secret_reference LIKE '%://%'",
            name=op.f("ck_shipping_accounts_secret_reference_uri"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["shipping_providers.id"],
            name=op.f("fk_shipping_accounts_provider_id_shipping_providers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_accounts")),
        sa.UniqueConstraint("id", "provider_id", name=op.f("uq_shipping_accounts_id_provider_id")),
        sa.UniqueConstraint(
            "provider_id",
            "account_name",
            name=op.f("uq_shipping_accounts_provider_id_account_name"),
        ),
    )
    op.create_table(
        "shipping_webhook_events",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("provider_id", BIGINT_ID, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("tracking_number", sa.String(length=64), nullable=True),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", JSON_DOC, nullable=False),
        sa.Column("headers_json", JSON_DOC, nullable=True),
        sa.Column("received_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", TIMESTAMPTZ, nullable=True),
        sa.Column(
            "processing_status",
            sa.String(length=16),
            server_default=sa.text("'RECEIVED'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "processing_status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED', 'IGNORED')",
            name=op.f("ck_shipping_webhook_events_processing_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_shipping_webhook_events_attempt_count_non_negative")
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64", name=op.f("ck_shipping_webhook_events_fingerprint_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["shipping_providers.id"],
            name=op.f("fk_shipping_webhook_events_provider_id_shipping_providers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_webhook_events")),
        sa.UniqueConstraint(
            "provider_id", "event_id", name=op.f("uq_shipping_webhook_events_provider_id_event_id")
        ),
        sa.UniqueConstraint(
            "provider_id",
            "fingerprint",
            name=op.f("uq_shipping_webhook_events_provider_id_fingerprint"),
        ),
    )
    op.create_index(
        op.f("ix_shipping_webhook_events_processing_status_received_at"),
        "shipping_webhook_events",
        ["processing_status", "received_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shipping_webhook_events_tracking_number"),
        "shipping_webhook_events",
        ["tracking_number"],
        unique=False,
    )

    op.create_table(
        "shipments",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", BIGINT_ID, nullable=False),
        sa.Column("shipping_account_id", BIGINT_ID, nullable=True),
        sa.Column("tracking_number", sa.String(length=64), nullable=True),
        sa.Column("service_code", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'DRAFT'"), nullable=False
        ),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("sender_phone", sa.String(length=32), nullable=True),
        sa.Column("sender_address_line", sa.String(length=500), nullable=True),
        sa.Column("sender_ward", sa.String(length=128), nullable=True),
        sa.Column("sender_district", sa.String(length=128), nullable=True),
        sa.Column("sender_province", sa.String(length=128), nullable=True),
        sa.Column("receiver_name", sa.String(length=255), nullable=True),
        sa.Column("receiver_phone", sa.String(length=32), nullable=True),
        sa.Column("receiver_address_line", sa.String(length=500), nullable=True),
        sa.Column("receiver_ward", sa.String(length=128), nullable=True),
        sa.Column("receiver_district", sa.String(length=128), nullable=True),
        sa.Column("receiver_province", sa.String(length=128), nullable=True),
        sa.Column("package_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cod_amount", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'VND'"), nullable=False),
        sa.Column("estimated_fee", MONEY, nullable=True),
        sa.Column("actual_fee", MONEY, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint("order_id <> ''", name=op.f("ck_shipments_order_id_not_empty")),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'READY_TO_CREATE', 'CREATED', 'READY_TO_PICK', 'PICKED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'DELIVERY_FAILED', 'RETURNING', 'RETURNED', 'CANCELLED')",
            name=op.f("ck_shipments_status_valid"),
        ),
        sa.CheckConstraint(
            "actual_fee IS NULL OR actual_fee >= 0",
            name=op.f("ck_shipments_actual_fee_non_negative"),
        ),
        sa.CheckConstraint("cod_amount >= 0", name=op.f("ck_shipments_cod_amount_non_negative")),
        sa.CheckConstraint(
            "estimated_fee IS NULL OR estimated_fee >= 0",
            name=op.f("ck_shipments_estimated_fee_non_negative"),
        ),
        sa.CheckConstraint("length(currency) = 3", name=op.f("ck_shipments_currency_iso")),
        sa.CheckConstraint(
            "package_count >= 0", name=op.f("ck_shipments_package_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["shipping_providers.id"],
            name=op.f("fk_shipments_provider_id_shipping_providers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shipping_account_id", "provider_id"],
            ["shipping_accounts.id", "shipping_accounts.provider_id"],
            name=op.f("fk_shipments_shipping_account_id_provider_id_shipping_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipments")),
        sa.UniqueConstraint("id", "provider_id", name=op.f("uq_shipments_id_provider_id")),
        sa.UniqueConstraint(
            "provider_id", "tracking_number", name=op.f("uq_shipments_provider_id_tracking_number")
        ),
    )
    op.create_index(op.f("ix_shipments_order_id"), "shipments", ["order_id"], unique=False)
    op.create_index(op.f("ix_shipments_status"), "shipments", ["status"], unique=False)

    op.create_table(
        "shipment_cod",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("shipment_id", BIGINT_ID, nullable=False),
        sa.Column("expected_amount", MONEY, nullable=False),
        sa.Column("collected_amount", MONEY, nullable=True),
        sa.Column("remitted_amount", MONEY, nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'VND'"), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("collected_at", TIMESTAMPTZ, nullable=True),
        sa.Column("remitted_at", TIMESTAMPTZ, nullable=True),
        sa.Column("remittance_reference", sa.String(length=128), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COLLECTED', 'REMITTED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name=op.f("ck_shipment_cod_status_valid"),
        ),
        sa.CheckConstraint(
            "collected_amount IS NULL OR collected_amount >= 0",
            name=op.f("ck_shipment_cod_collected_non_negative"),
        ),
        sa.CheckConstraint(
            "expected_amount >= 0", name=op.f("ck_shipment_cod_expected_non_negative")
        ),
        sa.CheckConstraint("length(currency) = 3", name=op.f("ck_shipment_cod_currency_iso")),
        sa.CheckConstraint(
            "remitted_amount IS NULL OR remitted_amount >= 0",
            name=op.f("ck_shipment_cod_remitted_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_cod_shipment_id_shipments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_cod")),
        sa.UniqueConstraint("shipment_id", name=op.f("uq_shipment_cod_shipment_id")),
    )
    op.create_table(
        "shipment_events",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("shipment_id", BIGINT_ID, nullable=False),
        sa.Column("provider_id", BIGINT_ID, nullable=False),
        sa.Column("canonical_status", sa.String(length=32), nullable=False),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("provider_event_id", sa.String(length=128), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", TIMESTAMPTZ, nullable=False),
        sa.Column("received_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("webhook_event_id", BIGINT_ID, nullable=True),
        sa.Column("metadata_json", JSON_DOC, nullable=True),
        sa.CheckConstraint(
            "canonical_status IN ('DRAFT', 'READY_TO_CREATE', 'CREATED', 'READY_TO_PICK', 'PICKED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'DELIVERY_FAILED', 'RETURNING', 'RETURNED', 'CANCELLED')",
            name=op.f("ck_shipment_events_canonical_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id", "provider_id"],
            ["shipments.id", "shipments.provider_id"],
            name=op.f("fk_shipment_events_shipment_id_provider_id_shipments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"],
            ["shipping_webhook_events.id"],
            name=op.f("fk_shipment_events_webhook_event_id_shipping_webhook_events"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_events")),
        sa.UniqueConstraint(
            "provider_id",
            "provider_event_id",
            name=op.f("uq_shipment_events_provider_id_provider_event_id"),
        ),
    )
    op.create_index(
        op.f("ix_shipment_events_shipment_id_occurred_at"),
        "shipment_events",
        ["shipment_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "shipment_fees",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("shipment_id", BIGINT_ID, nullable=False),
        sa.Column("fee_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'VND'"), nullable=False),
        sa.Column("provider_reference", sa.String(length=128), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            "amount >= 0 OR source = 'ADJUSTMENT'",
            name=op.f("ck_shipment_fees_amount_non_negative"),
        ),
        sa.CheckConstraint("fee_type <> ''", name=op.f("ck_shipment_fees_fee_type_not_empty")),
        sa.CheckConstraint(
            "source IN ('ESTIMATE', 'PROVIDER_ACTUAL', 'ADJUSTMENT')",
            name=op.f("ck_shipment_fees_source_valid"),
        ),
        sa.CheckConstraint("length(currency) = 3", name=op.f("ck_shipment_fees_currency_iso")),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_fees_shipment_id_shipments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_fees")),
    )
    op.create_index(
        op.f("ix_shipment_fees_shipment_id"), "shipment_fees", ["shipment_id"], unique=False
    )

    op.create_table(
        "shipment_packages",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("shipment_id", BIGINT_ID, nullable=False),
        sa.Column("package_index", sa.Integer(), nullable=False),
        sa.Column("weight_grams", sa.Integer(), nullable=False),
        sa.Column("length_cm", sa.Integer(), nullable=True),
        sa.Column("width_cm", sa.Integer(), nullable=True),
        sa.Column("height_cm", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("declared_value", MONEY, nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "declared_value IS NULL OR declared_value >= 0",
            name=op.f("ck_shipment_packages_declared_value_non_negative"),
        ),
        sa.CheckConstraint(
            "height_cm IS NULL OR height_cm > 0", name=op.f("ck_shipment_packages_height_positive")
        ),
        sa.CheckConstraint(
            "length_cm IS NULL OR length_cm > 0", name=op.f("ck_shipment_packages_length_positive")
        ),
        sa.CheckConstraint(
            "package_index >= 1", name=op.f("ck_shipment_packages_package_index_positive")
        ),
        sa.CheckConstraint("weight_grams > 0", name=op.f("ck_shipment_packages_weight_positive")),
        sa.CheckConstraint(
            "width_cm IS NULL OR width_cm > 0", name=op.f("ck_shipment_packages_width_positive")
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_shipment_packages_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_packages")),
        sa.UniqueConstraint(
            "shipment_id",
            "package_index",
            name=op.f("uq_shipment_packages_shipment_id_package_index"),
        ),
    )
    op.create_table(
        "shipment_reconciliation",
        sa.Column("id", BIGINT_ID, autoincrement=True, nullable=False),
        sa.Column("shipment_id", BIGINT_ID, nullable=False),
        sa.Column("provider_id", BIGINT_ID, nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("statement_reference", sa.String(length=128), nullable=True),
        sa.Column("expected_amount", MONEY, nullable=False),
        sa.Column("actual_amount", MONEY, nullable=False),
        sa.Column("difference_amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'VND'"), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("reconciled_at", TIMESTAMPTZ, nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            "kind IN ('COD', 'FEE')", name=op.f("ck_shipment_reconciliation_kind_valid")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'MATCHED', 'MISMATCH', 'RESOLVED')",
            name=op.f("ck_shipment_reconciliation_status_valid"),
        ),
        sa.CheckConstraint(
            "difference_amount = actual_amount - expected_amount",
            name=op.f("ck_shipment_reconciliation_difference_consistent"),
        ),
        sa.CheckConstraint(
            "length(currency) = 3", name=op.f("ck_shipment_reconciliation_currency_iso")
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id", "provider_id"],
            ["shipments.id", "shipments.provider_id"],
            name=op.f("fk_shipment_reconciliation_shipment_id_provider_id_shipments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment_reconciliation")),
    )
    op.create_index(
        op.f("ix_shipment_reconciliation_provider_id_statement_reference"),
        "shipment_reconciliation",
        ["provider_id", "statement_reference"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shipment_reconciliation_shipment_id"),
        "shipment_reconciliation",
        ["shipment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_shipment_reconciliation_shipment_id"), table_name="shipment_reconciliation"
    )
    op.drop_index(
        op.f("ix_shipment_reconciliation_provider_id_statement_reference"),
        table_name="shipment_reconciliation",
    )

    op.drop_table("shipment_reconciliation")
    op.drop_table("shipment_packages")
    op.drop_index(op.f("ix_shipment_fees_shipment_id"), table_name="shipment_fees")

    op.drop_table("shipment_fees")
    op.drop_index(op.f("ix_shipment_events_shipment_id_occurred_at"), table_name="shipment_events")

    op.drop_table("shipment_events")
    op.drop_table("shipment_cod")
    op.drop_index(op.f("ix_shipments_status"), table_name="shipments")
    op.drop_index(op.f("ix_shipments_order_id"), table_name="shipments")

    op.drop_table("shipments")
    op.drop_index(
        op.f("ix_shipping_webhook_events_tracking_number"), table_name="shipping_webhook_events"
    )
    op.drop_index(
        op.f("ix_shipping_webhook_events_processing_status_received_at"),
        table_name="shipping_webhook_events",
    )

    op.drop_table("shipping_webhook_events")
    op.drop_table("shipping_accounts")
    op.drop_table("shipping_providers")
    op.drop_index(
        op.f("ix_shipping_audit_logs_entity_type_entity_id_created_at"),
        table_name="shipping_audit_logs",
    )

    op.drop_table("shipping_audit_logs")
