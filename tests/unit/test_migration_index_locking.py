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

# Every way we know of to build an index from a migration, INCLUDING the ones that build
# one without the word "index" anywhere: in PostgreSQL a UNIQUE constraint, a PRIMARY KEY
# and a unique column all create an index under the same ACCESS EXCLUSIVE lock, and
# `create_unique_constraint` is ordinary alembic autogenerate output -- the likeliest way
# for this to be escaped by accident rather than on purpose.
#
# Deliberately broad, and a denylist (CLAUDE.md 12.2): an extra match costs the author one
# comment line, a missed one is a table locked during a deploy that nobody reviewed.
# Case-sensitive, because `re.IGNORECASE` here also matched `list.index(`.
BUILDS_INDEX = re.compile(
    r"create_index\s*\(|create_unique_constraint\s*\(|create_primary_key\s*\("
    r"|\bIndex\s*\(|\bUniqueConstraint\s*\(|\bPrimaryKeyConstraint\s*\("
    r"|unique\s*=\s*True"
)
# Raw DDL is matched separately so that only this half ignores case.
BUILDS_INDEX_SQL = re.compile(r"CREATE\s+(UNIQUE\s+)?INDEX|ADD\s+CONSTRAINT", re.IGNORECASE)


def builds_index(source: str) -> bool:
    return bool(BUILDS_INDEX.search(source) or BUILDS_INDEX_SQL.search(source))


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
    if not builds_index(source):
        return
    assert ACKNOWLEDGED.search(source), (
        f"{path.name} builds an index (directly, or via a unique/primary-key constraint, "
        "which creates one). That takes an ACCESS EXCLUSIVE lock on the table "
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
        # These build an index without the word "index" appearing anywhere.
        "op.create_unique_constraint('uq_x', 'shipments', ['order_id'])",
        "op.create_primary_key('pk_x', 'shipments', ['id'])",
        "batch.create_unique_constraint('uq_x', ['order_id'])",
        "op.add_column('shipments', sa.Column('ref', sa.String(), unique=True))",
        "sa.UniqueConstraint('provider_id', 'tracking_number')",
        'op.execute("ALTER TABLE shipments ADD CONSTRAINT uq_x UNIQUE (order_id)")',
    ],
)
def test_guard_sees_every_way_we_know_to_build_an_index(source):
    """The guard itself must be able to fail, or it proves nothing."""
    assert builds_index(source), source
    assert not ACKNOWLEDGED.search(source)
    assert ACKNOWLEDGED.search(source + "\n# INDEX_LOCK_REVIEWED: empty table here\n")


def test_prose_about_concurrently_is_not_an_acknowledgement():
    """What made the first version of this guard weaker than it claimed."""
    prose = '"""On a large table this needs CREATE INDEX CONCURRENTLY."""\nop.create_index(x)'
    assert builds_index(prose) and not ACKNOWLEDGED.search(prose)


def test_ordinary_list_index_is_not_mistaken_for_an_index_build():
    """`re.IGNORECASE` on the Python half used to match `names.index(0)`."""
    assert not builds_index("names = ['a']\nposition = names.index('a')\n")


def test_what_this_guard_does_not_catch():
    """Written down rather than implied: the marker is a word, not a review.

    A migration can satisfy this guard with a bare marker and no thought, and a build
    reached through a helper defined outside migrations/versions/ is not seen at all. The
    guard makes the question unavoidable; it cannot make the answer good.
    """
    bare = "op.create_index(x)\n# INDEX_LOCK_REVIEWED\n"
    assert builds_index(bare) and ACKNOWLEDGED.search(bare)
    assert not builds_index("helpers.add_my_index(op, 'shipments', ['a'])")
