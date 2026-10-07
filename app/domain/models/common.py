"""Provider-neutral value objects shared by the shipping domain.

Nothing in this module may reference a specific carrier's API, URL,
credential or status code.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""A string that is not empty after stripping surrounding whitespace."""


class DomainModel(BaseModel):
    """Base for mutable domain models: unknown fields are rejected."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ValueObject(BaseModel):
    """Base for immutable value objects."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )


class ShippingProviderCode(StrEnum):
    """Identifiers of shipping providers the gateway may route to.

    Declaring a code does not mean an adapter exists for it.
    """

    VIETTEL_POST = "VIETTEL_POST"
    SUPERSHIP = "SUPERSHIP"
    GHN = "GHN"
    GHTK = "GHTK"
    VIPORDER_FLEET = "VIPORDER_FLEET"


MONEY_MAX_DECIMAL_PLACES = 2
MONEY_MAX_INTEGER_DIGITS = 16
"""Matches the persistence limit NUMERIC(18,2) so a bad amount fails at the edge."""


class Money(ValueObject):
    """Monetary amount. Stored as Decimal; float input is rejected.

    At most 2 decimal places and 16 integer digits (the NUMERIC(18,2) column limit).
    """

    amount: Annotated[
        Decimal,
        Field(
            ge=0,
            max_digits=MONEY_MAX_INTEGER_DIGITS + MONEY_MAX_DECIMAL_PLACES,
            decimal_places=MONEY_MAX_DECIMAL_PLACES,
        ),
    ]
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] = "VND"

    @field_validator("amount", mode="before")
    @classmethod
    def _reject_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("amount must not be a float; pass int, str or Decimal")
        return value


class Address(ValueObject):
    """Sender or receiver contact and address, in provider-neutral form."""

    name: NonEmptyStr
    phone: NonEmptyStr
    address_line: NonEmptyStr
    ward: str | None = None
    district: str | None = None
    province: NonEmptyStr
