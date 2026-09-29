"""Portable column types for the shipping schema.

Every type here has one job: keep behaviour identical on PostgreSQL (target)
and SQLite (local tests / dev) without the application having to care.
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import JSON, BigInteger, DateTime, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

MONEY_PRECISION = 18
MONEY_SCALE = 2
_MONEY_QUANTUM = Decimal(1).scaleb(-MONEY_SCALE)  # Decimal("0.01")
_MONEY_FACTOR = 10**MONEY_SCALE
_MONEY_MAX = Decimal(10) ** (MONEY_PRECISION - MONEY_SCALE)

# Surrogate keys: BIGINT on PostgreSQL; SQLite only auto-increments INTEGER.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")

# JSON payloads: JSONB on PostgreSQL, JSON (TEXT) on SQLite.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class MoneyType(TypeDecorator):
    """Exact money: NUMERIC(18,2) on PostgreSQL, integer minor units on SQLite.

    SQLite has no exact decimal type (NUMERIC affinity falls back to REAL), so
    on SQLite the value is stored as BIGINT = amount x 100. Floats are rejected
    and amounts with more than two decimal places are rejected rather than
    silently rounded.
    """

    impl = Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(BigInteger())
        return dialect.type_descriptor(Numeric(MONEY_PRECISION, MONEY_SCALE, asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        amount = to_money(value)
        if dialect.name == "sqlite":
            return int(amount * _MONEY_FACTOR)
        return amount

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "sqlite":
            return (Decimal(int(value)) / _MONEY_FACTOR).quantize(_MONEY_QUANTUM)
        return Decimal(value).quantize(_MONEY_QUANTUM)


def to_money(value) -> Decimal:
    """Validate and normalise a money value to a 2-decimal Decimal."""
    if isinstance(value, bool | float):
        raise TypeError("money must be Decimal, int or str, never float/bool")
    try:
        amount = Decimal(value) if not isinstance(value, Decimal) else value
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError("money must be finite")
    quantized = amount.quantize(_MONEY_QUANTUM)
    if quantized != amount:
        raise ValueError(f"money has more than {MONEY_SCALE} decimal places: {value!r}")
    if abs(quantized) >= _MONEY_MAX:
        raise ValueError(f"money exceeds NUMERIC({MONEY_PRECISION},{MONEY_SCALE}): {value!r}")
    return quantized


class UTCDateTime(TypeDecorator):
    """Timezone-aware timestamps, always stored and returned in UTC.

    PostgreSQL uses TIMESTAMPTZ. SQLite has no timezone storage, so values are
    stored as naive UTC and re-tagged with UTC on the way out. Naive datetimes
    are rejected on bind to avoid ambiguous local times.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
