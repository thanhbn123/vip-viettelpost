# COD / phí / đối soát — nền tảng (G10)

**Chỉ là nền ghi số**, không phải hệ kế toán. Quy tắc nghiệp vụ (ai sở hữu tiền COD, khi nào coi là tất toán, ai được điều chỉnh phí) **chưa được chủ dự án chốt** (R-011) nên không được mã hoá.

| Việc | Endpoint | Luật máy móc (D-029, D-030) |
|---|---|---|
| Xem | `GET /shipments/{id}/finance` | COD dự kiến / đã thu / đã nộp + trạng thái, phí ước tính (lúc tạo đơn) / phí thực tế, các dòng phí, các lần đối soát |
| Hãng đã thu COD | `POST /shipments/{id}/cod/collected` `{amount, collected_at?}` | Chỉ vận đơn có COD. Không được thấp hơn số đã nộp (422). Đã `REMITTED` → 409 |
| Hãng đã nộp COD | `POST /shipments/{id}/cod/remitted` `{amount, reference, remitted_at?}` | Phải thu trước (409); không vượt số đã thu (422); đã `REMITTED` → 409 (sửa qua đối soát) |
| Dòng phí | `POST /shipments/{id}/fees` `{fee_type, source, amount, note?, provider_reference?}` | `source`: `PROVIDER_ACTUAL` (≥ 0) hoặc `ADJUSTMENT` (được âm, **bắt buộc ghi chú**). `actual_fee` = tổng hai loại, không được < 0 |
| Đối soát | `POST /shipments/{id}/reconciliations` `{kind: COD\|FEE, actual_amount, statement_reference?}` | Dự kiến: COD dự kiến / phí ước tính (vận đơn không COD / chưa có phí ước tính → 422). `chênh = thực tế − dự kiến`; 0 → `MATCHED`, khác → `MISMATCH` |
| Chốt chênh lệch | `POST /reconciliations/{id}/resolve` `{note}` | Chỉ từ `MISMATCH` → `RESOLVED` |

- **Trạng thái COD luôn suy lại từ ba con số** sau mỗi lần ghi (`derive_cod_status`): chưa thu → `PENDING`; đã nộp == đã thu → `REMITTED`; đã thu == dự kiến → `COLLECTED`; còn lại → `PARTIAL`. Không bao giờ để trạng thái lệch số (verifier PR #14).
- Chưa xử lý (thuộc R-011): COD của vận đơn đã huỷ không tự chuyển `CANCELLED`; thời điểm thu/nộp ở tương lai không bị chặn.
- Tiền: Decimal chính xác, tối đa 2 số lẻ, cùng đơn vị với vận đơn; số thực (float) bị từ chối.
- Mọi thay đổi ghi audit có trước/sau (`COD_CHANGED`, `FEE_RECORDED`, `RECONCILIATION_ADJUSTED`, `RECONCILIATION_RECORDED`).
- Chưa có xác thực bên gọi (G12): **không** mở các endpoint này ra ngoài trước G12.
