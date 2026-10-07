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

# One marker, and only this marker. The first version of this guard also accepted the word
# CONCURRENTLY anywhere in the file, which meant a migration could satisfy it by MENTIONING
# the problem in prose while still doing a plain create_index -- shp_0004 passed exactly
# that way. Writing the marker is a deliberate act; writing a word is not.
ACKNOWLEDGED = re.compile(r"INDEX_LOCK_REVIEWED")

# Every way we know of to build an index from a migration. Deliberately broad, and a
# denylist (CLAUDE.md 12.2): an extra match costs the author one comment line, while a
# missed one is an index built under a table lock that nobody reviewed. `create_index`
# unqualified also catches `from alembic.op import create_index` and any local alias.
BUILDS_INDEX = re.compile(
    r"create_index\s*\(|sa\.Index\s*\(|\bIndex\s*\(|CREATE\s+INDEX",
    re.IGNORECASE,
)


def migration_files() -> list[Path]:
    """Every migration module, not just the ones named shp_*.

    alembic's file_template is %%(rev)s, so a revision whose id does not start with "shp_"
    would be skipped by a name filter -- silently, while the "did we find any files"
    assertion below still passed. A guard that quietly stops covering new work is the
    failure this whole file is about.
    """
    files = sorted(
        p for p in VERSIONS.glob("*.py") if p.is_file() and p.name != "__init__.py"
    )
    assert files, "no migration files found — this guard would pass vacuously"
    return files


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.stem)
def test_index_building_migrations_acknowledge_the_table_lock(path: Path):
    source = path.read_text(encoding="utf-8")
    if not BUILDS_INDEX.search(source):
        return
    assert ACKNOWLEDGED.search(source), (
        f"{path.name} builds an index. That takes an ACCESS EXCLUSIVE lock on the table "
        "for the whole build, which is free on an empty table and an outage on a full "
        "one. Write CREATE INDEX CONCURRENTLY, or say why the plain form is right for "
        "this table, and mark the reason with INDEX_LOCK_REVIEWED."
    )


@pytest.mark.parametrize(
    "source",
    [
        "op.create_index('ix_x', 'shipments', ['a'])",
        "op.create_index(\n    'ix_x', 'shipments', ['a'])",  # newline before the paren
        "create_index('ix_x', 'shipments', ['a'])",  # from alembic.op import create_index
        "op.create_table('t', sa.Column('a'), sa.Index('ix_x', 'a'))",
        "sa.Index('ix_x', 'a').create(bind)",
        'op.execute("CREATE INDEX ix_x ON shipments (a)")',
        'op.execute("create index ix_x on shipments (a)")',
    ],
)
def test_guard_sees_every_way_we_know_to_build_an_index(source):
    """The guard itself must be able to fail, or it proves nothing."""
    assert BUILDS_INDEX.search(source), source
    assert not ACKNOWLEDGED.search(source)
    assert ACKNOWLEDGED.search(source + "\n# INDEX_LOCK_REVIEWED: empty table here\n")


def test_prose_about_concurrently_is_not_an_acknowledgement():
    """What made the first version of this guard weaker than it claimed."""
    prose = '"""On a large table this needs CREATE INDEX CONCURRENTLY."""\nop.create_index(x)'
    assert BUILDS_INDEX.search(prose) and not ACKNOWLEDGED.search(prose)
