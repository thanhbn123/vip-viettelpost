"""Viettel Post-specific request options, carried in ``provider_options`` of the core DTOs.

Everything here exists only because the Viettel Post Partner API needs it
(https://partner2.viettelpost.vn/document, checked 2026-09-29). None of it belongs in the
provider-neutral domain.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PositiveId = Annotated[int, Field(strict=True, gt=0)]
NonNegativeVnd = Annotated[int, Field(strict=True, ge=0)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Options(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VtpLocationIds(_Options):
    """Viettel Post location catalogue IDs for one address.

    The Partner API routes by numeric IDs, not by names. ``district_id`` may be ``None``:
    the official create-order sample sends ``SENDER_DISTRICT: null`` for 2-level addresses.
    Name-to-ID lookup is not implemented (see docs/INTEGRATION_NOTES.md).
    """

    province_id: PositiveId
    district_id: PositiveId | None
    ward_id: PositiveId


class VtpItem(_Options):
    """One line of ``LIST_ITEM`` (goods in the parcel, not a physical package)."""

    name: Text
    quantity: Annotated[int, Field(strict=True, gt=0)]
    price_vnd: NonNegativeVnd
    weight_grams: Annotated[int, Field(strict=True, gt=0)]


class ViettelPostOptions(_Options):
    sender_location: VtpLocationIds
    receiver_location: VtpLocationIds
    # PRODUCT_TYPE: "TH" (thư / document) or "HH" (hàng hoá / goods). VIPORDER ships goods.
    product_type: Literal["TH", "HH"] = "HH"
    # TYPE / NATIONAL_TYPE: 1 = domestic, 0 = international (official page). The domain
    # Address has no country, and the gateway serves domestic Vietnam shipments.
    price_table_type: Literal[0, 1] = 1
    # ORDER_PAYMENT 1..4 is required to create an order. Its business meaning (who pays the
    # fee, whether COD is collected) is an owner decision, so there is no default.
    order_payment: Literal[1, 2, 3, 4] | None = None
    extra_service_codes: Text | None = None
    product_name: Text | None = None
    product_quantity: Annotated[int, Field(strict=True, gt=0)] | None = None
    # Declared goods value; defaults to the sum of the packages' declared values.
    product_price_vnd: NonNegativeVnd | None = None
    items: list[VtpItem] = Field(default_factory=list)
