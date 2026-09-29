"""shp_0003: at most one ACTIVE shipment per (provider, order).

A shipment is active unless its status is DRAFT (never created at the provider, e.g.
the provider rejected it) or CANCELLED. The partial unique index is the database-level
guard against creating the same VIPORDER order twice at a carrier when two requests
race (CR-SHP-001 G06, D-022).

Portable partial index: PostgreSQL ``WHERE`` and SQLite ``WHERE`` (SQLite >= 3.8).
Upgrade fails if duplicate active shipments already exist; resolve them first.

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
