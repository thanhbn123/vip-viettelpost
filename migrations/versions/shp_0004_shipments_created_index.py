"""shp_0004: index for the operational list ordering (created_at DESC, id DESC).

``GET /shipments`` pages newest-first; without this index every page sorts the whole
table (verifier note on PR #12). Plain B-tree, both dialects.

INDEX_LOCK_REVIEWED: this takes an ACCESS EXCLUSIVE lock on ``shipments`` for the whole
build. On the empty staging table that is instant. It is NOT safe on a populated
production table, and nothing here makes it safe: the plain form is kept only because
CREATE INDEX CONCURRENTLY cannot run inside the migration's transaction, so using it
means taking this index out of alembic and into a reviewed production runbook -- which
does not exist yet (docs/READINESS_REVIEW_MAIN.md, production blocker 1). Until it does,
applying this revision to a large ``shipments`` table needs a maintenance window.

This file used to satisfy the index-lock guard merely by containing the word
CONCURRENTLY in prose while doing a plain create_index; the guard now requires the
marker above.

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
