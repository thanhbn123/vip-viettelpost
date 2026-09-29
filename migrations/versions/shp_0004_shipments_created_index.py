"""shp_0004: index for the operational list ordering (created_at DESC, id DESC).

``GET /shipments`` pages newest-first; without this index every page sorts the whole
table (verifier note on PR #12). Plain B-tree, both dialects. Building it takes a
write lock on ``shipments`` for the duration; fine for the (empty) staging table. On a
large production table this needs a reviewed runbook (CREATE INDEX CONCURRENTLY).

Revision ID: shp_0004_shipments_created_index
Revises: shp_0003_active_order_guard
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "shp_0004_shipments_created_index"
down_revision: str | None = "shp_0003_active_order_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_shipments_created_at_id"), "shipments", ["created_at", "id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shipments_created_at_id"), table_name="shipments")
