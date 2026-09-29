"""shp_0002: provider events without canonical status + durable webhook processing.

CR-SHP-001 G05 integration (see docs/INTEGRATION_NOTES.md, docs/DECISIONS.md):

shipment_events
  * canonical_status becomes NULLABLE: an unknown / unmapped provider status is still
    recorded, but never given a guessed canonical status (D-005).
  * occurred_at becomes NULLABLE: Viettel Post sends ORDER_STATUSDATE without timezone
    and the official page does not state one, so no aware time exists unless configured
    (D-006). received_at (NOT NULL) always holds the gateway receive time.
  * new: requires_review, occurred_at_raw, provider_status_name.
  * new CHECK: canonical_status IS NOT NULL OR requires_review.

shipping_webhook_events
  * new: provider_status, provider_status_name, canonical_status, requires_review,
    fingerprint_basis, occurred_at_raw, occurred_at, shipment_id (FK SET NULL),
    processing_started_at.

shipping_providers
  * seeds VIETTEL_POST (the only provider with an adapter).

Self-contained (no application imports). SQLite uses batch mode (table rebuild).

Downgrade refuses to run while rows exist that the old schema cannot hold
(events without canonical status or without occurred_at): it never deletes data.

Revision ID: shp_0002_webhook_processing
Revises: shp_0001_shipping_gateway
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "shp_0002_webhook_processing"
down_revision: str | None = "shp_0001_shipping_gateway"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TIMESTAMPTZ = sa.DateTime(timezone=True)
STATUSES = (
    "'DRAFT', 'READY_TO_CREATE', 'CREATED', 'READY_TO_PICK', 'PICKED', 'IN_TRANSIT', "
    "'OUT_FOR_DELIVERY', 'DELIVERED', 'DELIVERY_FAILED', 'RETURNING', 'RETURNED', 'CANCELLED'"
)


def upgrade() -> None:
    with op.batch_alter_table("shipment_events") as batch:
        batch.alter_column("canonical_status", existing_type=sa.String(32), nullable=True)
        batch.alter_column("occurred_at", existing_type=TIMESTAMPTZ, nullable=True)
        batch.add_column(
            sa.Column("requires_review", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(sa.Column("occurred_at_raw", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("provider_status_name", sa.String(length=128), nullable=True))
        batch.create_check_constraint(
            op.f("ck_shipment_events_status_or_review"),
            "canonical_status IS NOT NULL OR requires_review",
        )

    with op.batch_alter_table("shipping_webhook_events") as batch:
        batch.add_column(sa.Column("provider_status", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("provider_status_name", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("canonical_status", sa.String(length=32), nullable=True))
        batch.add_column(
            sa.Column("requires_review", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(sa.Column("fingerprint_basis", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("occurred_at_raw", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("occurred_at", TIMESTAMPTZ, nullable=True))
        batch.add_column(sa.Column("shipment_id", BIGINT_ID, nullable=True))
        batch.add_column(sa.Column("processing_started_at", TIMESTAMPTZ, nullable=True))
        batch.create_foreign_key(
            op.f("fk_shipping_webhook_events_shipment_id_shipments"),
            "shipments",
            ["shipment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            op.f("ck_shipping_webhook_events_canonical_status_valid"),
            f"canonical_status IN ({STATUSES})",
        )
        batch.create_index(op.f("ix_shipping_webhook_events_shipment_id"), ["shipment_id"])

    providers = sa.table(
        "shipping_providers",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(providers, [{"code": "VIETTEL_POST", "name": "Viettel Post", "enabled": True}])


def downgrade() -> None:
    bind = op.get_bind()
    blocking = bind.execute(
        sa.text(
            "SELECT count(*) FROM shipment_events "
            "WHERE canonical_status IS NULL OR occurred_at IS NULL"
        )
    ).scalar_one()
    if blocking:
        raise RuntimeError(
            f"shp_0002 downgrade refused: {blocking} shipment_events rows have no canonical "
            "status or no occurred_at and cannot be represented by shp_0001. Export or resolve "
            "them first; this migration never deletes data."
        )

    with op.batch_alter_table("shipping_webhook_events") as batch:
        batch.drop_index(op.f("ix_shipping_webhook_events_shipment_id"))
        batch.drop_constraint(
            op.f("ck_shipping_webhook_events_canonical_status_valid"), type_="check"
        )
        batch.drop_constraint(
            op.f("fk_shipping_webhook_events_shipment_id_shipments"), type_="foreignkey"
        )
        for column in (
            "processing_started_at",
            "shipment_id",
            "occurred_at",
            "occurred_at_raw",
            "fingerprint_basis",
            "requires_review",
            "canonical_status",
            "provider_status_name",
            "provider_status",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("shipment_events") as batch:
        batch.drop_constraint(op.f("ck_shipment_events_status_or_review"), type_="check")
        batch.drop_column("provider_status_name")
        batch.drop_column("occurred_at_raw")
        batch.drop_column("requires_review")
        batch.alter_column("occurred_at", existing_type=TIMESTAMPTZ, nullable=False)
        batch.alter_column("canonical_status", existing_type=sa.String(32), nullable=False)

    # Seed removal fails (FK RESTRICT) if shipments reference the provider: by design.
    op.execute(sa.text("DELETE FROM shipping_providers WHERE code = 'VIETTEL_POST'"))
