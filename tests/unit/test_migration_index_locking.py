"""M4: a migration that builds an index must say what it does to a live table.

`op.create_index` takes an ACCESS EXCLUSIVE lock on the table for the whole build. On the
empty staging database that is instant, so nothing here ever hurts — which is exactly the
problem: the first time it hurts is on a production table with rows in it, during a deploy,
with no warning anywhere in the review.

This is a fail-closed guard. A migration that adds an index and says nothing fails the
suite; the author then either writes CONCURRENTLY, or writes down why the plain form is
fine for that table. Forgetting is loud, which is the direction a guard has to fail in
(CLAUDE.md 12.2).
"""

import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
# Either promise: the index is built without the long lock, or the lock was considered.
ACKNOWLEDGED = re.compile(r"CONCURRENTLY|INDEX_LOCK_REVIEWED", re.IGNORECASE)
CREATES_INDEX = re.compile(r"\bop\.create_index\s*\(")


def migration_files() -> list[Path]:
    files = sorted(p for p in VERSIONS.glob("shp_*.py") if p.is_file())
    assert files, "no migration files found — this guard would pass vacuously"
    return files


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.stem)
def test_index_building_migrations_acknowledge_the_table_lock(path: Path):
    source = path.read_text(encoding="utf-8")
    if not CREATES_INDEX.search(source):
        return
    assert ACKNOWLEDGED.search(source), (
        f"{path.name} builds an index with op.create_index, which locks the table for the "
        "whole build. Use CREATE INDEX CONCURRENTLY, or state why the plain form is safe "
        "for this table and mark it with INDEX_LOCK_REVIEWED."
    )


def test_guard_rejects_an_unacknowledged_migration(tmp_path):
    """The guard itself must be able to fail, or it proves nothing."""
    silent = "def upgrade():\n    op.create_index('ix_x', 'shipments', ['a'])\n"
    assert CREATES_INDEX.search(silent) and not ACKNOWLEDGED.search(silent)
    reviewed = silent + "# INDEX_LOCK_REVIEWED: table is empty at this revision\n"
    assert ACKNOWLEDGED.search(reviewed)
