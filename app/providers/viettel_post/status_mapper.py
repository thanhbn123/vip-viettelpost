"""Viettel Post ORDER_STATUS -> VIPORDER canonical status.

Source of truth (verified 2026-09-29):
    https://partner2.viettelpost.vn/document/webhook
    section "Bảng danh sách trạng thái" and the "Lưu ý" paragraph on final statuses.

Rules:
- Only the 21 codes published in that table are "known".
- A known code is mapped to a canonical status only when the official name/description
  corresponds unambiguously. Known codes without an unambiguous canonical equivalent
  return ``canonical_status=None`` and must NOT change the shipment status.
- Any other code is "unknown": it is preserved verbatim, never defaulted to a
  canonical status (in particular never to IN_TRANSIT), and flagged for review.
"""

from dataclasses import dataclass

from app.domain.models.shipment import ShipmentStatus

SOURCE_URL = "https://partner2.viettelpost.vn/document/webhook"


@dataclass(frozen=True)
class VtpStatusDefinition:
    code: str
    name: str
    description: str
    canonical_status: ShipmentStatus | None


@dataclass(frozen=True)
class StatusMappingResult:
    provider_status: str
    canonical_status: ShipmentStatus | None
    is_known: bool
    is_terminal: bool
    provider_status_name: str | None

    @property
    def requires_review(self) -> bool:
        """True when the shipment status must not be changed automatically."""
        return self.canonical_status is None


_S = ShipmentStatus

# (code, official name, official description, canonical status or None)
_DEFINITIONS: tuple[tuple[str, str, str, ShipmentStatus | None], ...] = (
    ("101", "Viettel Post hủy lấy hàng", "Viettel Post hủy lấy hàng", _S.CANCELLED),
    # No canonical "pickup failed" status; READY_TO_PICK / DELIVERY_FAILED would be a guess.
    ("102", "Lấy hàng thất bại", "Lấy hàng thất bại", None),
    ("103", "Điều phối bưu cục lấy hàng", "Điều phối bưu cục lấy hàng", _S.READY_TO_PICK),
    ("104", "Lấy hàng điều phối bưu tá", "Lấy hàng điều phối bưu tá", _S.READY_TO_PICK),
    ("107", "Đối tác yêu cầu hủy", "Đối tác yêu cầu hủy qua API", _S.CANCELLED),
    ("200", "Lấy hàng thành công", "Lấy hàng thành công", _S.PICKED),
    ("201", "Viettel Post hủy đơn hàng", "Viettel Post hủy đơn hàng", _S.CANCELLED),
    # Waybill edit: not a movement of the parcel.
    ("202", "Sửa phiếu gửi", "Sửa phiếu gửi", None),
    ("300", "Khai thác đi", "Đóng tải", _S.IN_TRANSIT),
    ("400", "Khai thác đến", "Bàn giao hoặc nhận bàn giao", _S.IN_TRANSIT),
    ("500", "Giao bưu tá đi phát", "Phân công bưu tá đi giao hàng", _S.OUT_FOR_DELIVERY),
    ("501", "Thành công – Phát thành công", "Thành công - Phát thành công", _S.DELIVERED),
    # Destroyed at customer's request: final, but neither CANCELLED nor RETURNED exactly.
    ("503", "Tiêu hủy – Theo yêu cầu khách hàng", "Hủy - Theo yêu cầu khách hàng", None),
    (
        "504",
        "Thành công – Chuyển trả người gửi (Đơn hàng hoàn)",
        "Thành công - Chuyển hoàn lại cho người gửi",
        _S.RETURNED,
    ),
    # Used both for "receiver refused" and "sender requested return" (reason code 43).
    ("505", "Yêu cầu chuyển hoàn", "Yêu cầu chuyển hoàn", None),
    (
        "506",
        "Phát thất bại",
        "Phát thất bại - Khách hàng nghỉ, không có nhà/ Không nghe máy/ Hẹn giao lại",
        _S.DELIVERY_FAILED,
    ),
    (
        "507",
        "Khách hàng đến bưu cục nhận",
        "Phát thất bại - Khách hàng đến bưu cục nhận",
        _S.DELIVERY_FAILED,
    ),
    # A request to re-deliver; does not state that a courier is out again.
    ("508", "Phát tiếp", "Đơn vị yêu cầu phát tiếp", None),
    ("509", "Chuyển tiếp bưu cục khác", "Chuyển tiếp bưu cục khác", _S.IN_TRANSIT),
    ("515", "Duyệt hoàn", "Bưu cục phát duyệt hoàn", _S.RETURNING),
    ("550", "Phát tiếp", "Khách hàng yêu cầu phát tiếp", None),
)

VTP_STATUS_DEFINITIONS: dict[str, VtpStatusDefinition] = {
    code: VtpStatusDefinition(code, name, description, canonical)
    for code, name, description, canonical in _DEFINITIONS
}

# Final statuses per the "Lưu ý" paragraph of the official page.
# The status table additionally marks 104 as final; that contradicts both the paragraph
# and the flow (104 precedes 200 "Lấy hàng thành công"), so 104 is NOT treated as final.
# Recorded in docs/STATUS_MAPPING.md as a point to confirm with Viettel Post.
VTP_TERMINAL_STATUSES: frozenset[str] = frozenset({"101", "107", "201", "501", "503", "504"})

# Known code -> canonical status, only where an unambiguous mapping exists.
STATUS_MAP: dict[str, ShipmentStatus] = {
    code: d.canonical_status
    for code, d in VTP_STATUS_DEFINITIONS.items()
    if d.canonical_status is not None
}


def normalize_provider_status(value: object) -> str | None:
    """Return ORDER_STATUS as a decimal string, or None if it is not an integer code.

    The official doc types ORDER_STATUS as Integer. A digit-only string is also accepted
    (harmless, avoids dropping an otherwise valid event); bools, floats and negatives are
    rejected.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isascii() and stripped.isdigit():
            return str(int(stripped))
    return None


def map_status(provider_status: str | int) -> StatusMappingResult:
    """Map a Viettel Post ORDER_STATUS. Never guesses for unknown codes."""
    code = normalize_provider_status(provider_status)
    key = code if code is not None else str(provider_status)
    definition = VTP_STATUS_DEFINITIONS.get(key)
    if definition is None:
        return StatusMappingResult(
            provider_status=key,
            canonical_status=None,
            is_known=False,
            is_terminal=False,
            provider_status_name=None,
        )
    return StatusMappingResult(
        provider_status=key,
        canonical_status=definition.canonical_status,
        is_known=True,
        is_terminal=key in VTP_TERMINAL_STATUSES,
        provider_status_name=definition.name,
    )
