import pytest

from app.domain.models.shipment import ShipmentStatus
from app.providers.viettel_post.status_mapper import (
    STATUS_MAP,
    VTP_STATUS_DEFINITIONS,
    VTP_TERMINAL_STATUSES,
    map_status,
)

# The 21 codes of "Bảng danh sách trạng thái", https://partner2.viettelpost.vn/document/webhook
OFFICIAL_CODES = {
    "101", "102", "103", "104", "107", "200", "201", "202", "300", "400",
    "500", "501", "503", "504", "505", "506", "507", "508", "509", "515", "550",
}  # fmt: skip


def test_known_codes_are_exactly_the_official_table():
    assert set(VTP_STATUS_DEFINITIONS) == OFFICIAL_CODES
    assert len(OFFICIAL_CODES) == 21


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (101, ShipmentStatus.CANCELLED),
        (103, ShipmentStatus.READY_TO_PICK),
        (104, ShipmentStatus.READY_TO_PICK),
        (107, ShipmentStatus.CANCELLED),
        (200, ShipmentStatus.PICKED),
        (201, ShipmentStatus.CANCELLED),
        (300, ShipmentStatus.IN_TRANSIT),
        (400, ShipmentStatus.IN_TRANSIT),
        (500, ShipmentStatus.OUT_FOR_DELIVERY),
        (501, ShipmentStatus.DELIVERED),
        (504, ShipmentStatus.RETURNED),
        (506, ShipmentStatus.DELIVERY_FAILED),
        (507, ShipmentStatus.DELIVERY_FAILED),
        (509, ShipmentStatus.IN_TRANSIT),
        (515, ShipmentStatus.RETURNING),
    ],
)
def test_known_status_mapping(code, expected):
    result = map_status(code)
    assert result.is_known is True
    assert result.canonical_status is expected
    assert result.requires_review is False
    assert result.provider_status == str(code)


@pytest.mark.parametrize("code", ["102", "202", "503", "505", "508", "550"])
def test_known_but_ambiguous_codes_do_not_change_status(code):
    result = map_status(code)
    assert result.is_known is True
    assert result.canonical_status is None
    assert result.requires_review is True
    assert result.provider_status_name


@pytest.mark.parametrize("code", [0, 105, 999, "777", 12345])
def test_unknown_status_is_preserved_and_not_mapped(code):
    result = map_status(code)
    assert result.is_known is False
    assert result.canonical_status is None
    assert result.requires_review is True
    assert result.provider_status == str(code)
    assert result.is_terminal is False


def test_unknown_status_never_defaults_to_in_transit():
    for code in range(1000):
        if str(code) in VTP_STATUS_DEFINITIONS:
            continue
        assert map_status(code).canonical_status is None


def test_string_and_int_codes_map_identically():
    assert map_status("501") == map_status(501)
    assert map_status(" 501 ") == map_status(501)


def test_non_integer_status_is_unknown_not_guessed():
    result = map_status("DELIVERED")
    assert result.is_known is False
    assert result.canonical_status is None
    assert result.provider_status == "DELIVERED"


def test_terminal_statuses_follow_official_note():
    assert VTP_TERMINAL_STATUSES == {"101", "107", "201", "501", "503", "504"}
    assert map_status(501).is_terminal is True
    # Table marks 104 as final but the prose list and the flow do not; see STATUS_MAPPING.md.
    assert map_status(104).is_terminal is False
    assert map_status(500).is_terminal is False


def test_status_map_only_contains_mapped_known_codes():
    assert set(STATUS_MAP) <= OFFICIAL_CODES
    assert all(isinstance(v, ShipmentStatus) for v in STATUS_MAP.values())
