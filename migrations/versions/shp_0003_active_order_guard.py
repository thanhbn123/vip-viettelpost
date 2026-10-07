"""shp_0003: at most one ACTIVE shipment per (provider, order) + operation claim.

A shipment is active unless its status is DRAFT (never created at the provider, e.g.
the provider rejected it) or CANCELLED. The partial unique index is the database-level
guard against creating the same VIPORDER order twice at a carrier when two requests
race (CR-SHP-001 G06, D-022).

Also adds ``shipments.operation_lock`` / ``operation_lock_at``: a short claim taken with
a conditional UPDATE before a provider mutation (cancel) so two concurrent requests
cannot both call the carrier, and the final write only succeeds if the status did not
change meanwhile (D-028). Nullable, no default: existing rows are unaffected.

Portable partial index: PostgreSQL ``WHERE`` and SQLite ``WHERE`` (SQLite >= 3.8).
Upgrade fails if duplicate active shipments already exist; resolve them first.

INDEX_LOCK_REVIEWED: the plain form is deliberate here. This index is the guard that
stops two races from creating the same order twice at the carrier, so it has to be in
place before any row can slip past it -- CREATE INDEX CONCURRENTLY leaves a window where
it is not enforcing, and it cannot run inside this migration's transaction. On a
populated ``shipments`` table the build takes a write lock for its duration: that needs a
maintenance window, which is part of the production runbook that does not exist yet
(docs/READINESS_REVIEW_MAIN.md, production blocker 1).

Revision ID: shp_0003_active_order_guard
Revises: shp_0002_webhook_processing
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "shp_0003_active_order_guard"
down_revision: str | None = "shp_0002_webhook_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE = sa.text("status NOT IN ('DRAFT', 'CANCELLED')")


def upgrade() -> None:
    with op.batch_alter_table("shipments") as batch:
        batch.add_column(sa.Column("operation_lock", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("operation_lock_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("uq_shipments_active_provider_order"),
        "shipments",
        ["provider_id", "order_id"],
        unique=True,
        postgresql_where=ACTIVE,
        sqlite_where=ACTIVE,
    )


def downgrade() -> None:
    op.drop_index(op.f("uq_shipments_active_provider_order"), table_name="shipments")
    with op.batch_alter_table("shipments") as batch:
        batch.drop_column("operation_lock_at")
        batch.drop_column("operation_lock")
