# COD / phí / đối soát — nền tảng (G10)

**Chỉ là nền ghi số**, không phải hệ kế toán. Quy tắc nghiệp vụ (ai sở hữu tiền COD, khi nào coi là tất toán, ai được điều chỉnh phí) **chưa được chủ dự án chốt** (R-011) nên không được mã hoá.

| Việc | Endpoint | Luật máy móc (D-029, D-030) |
|---|---|---|
| Xem | `GET /shipments/{id}/finance` | COD dự kiến / đã thu / đã nộp + trạng thái, phí ước tính (lúc tạo đơn) / phí thực tế, các dòng phí, các lần đối soát |
| Hãng đã thu COD | `POST /shipments/{id}/cod/collected` `{amount, collected_at?}` | Chỉ vận đơn có COD. `đã thu == dự kiến` → `COLLECTED`, khác → `PARTIAL`. Đã `REMITTED` → 409 |
| Hãng đã nộp COD | `POST /shipments/{id}/cod/remitted` `{amount, reference, remitted_at?}` | Phải thu trước (409). `đã nộp == đã thu` → `REMITTED` |
| Dòng phí | `POST /shipments/{id}/fees` `{fee_type, source, amount, note?, provider_reference?}` | `source`: `PROVIDER_ACTUAL` (≥ 0) hoặc `ADJUSTMENT` (được âm, **bắt buộc ghi chú**). `actual_fee` = tổng hai loại, không được < 0 |
| Đối soát | `POST /shipments/{id}/reconciliations` `{kind: COD\|FEE, actual_amount, statement_reference?}` | Dự kiến: COD dự kiến / phí ước tính. `chênh = thực tế − dự kiến`; 0 → `MATCHED`, khác → `MISMATCH` |
| Chốt chênh lệch | `POST /reconciliations/{id}/resolve` `{note}` | Chỉ từ `MISMATCH` → `RESOLVED` |

- Tiền: Decimal chính xác, tối đa 2 số lẻ, cùng đơn vị với vận đơn; số thực (float) bị từ chối.
- Mọi thay đổi ghi audit có trước/sau (`COD_CHANGED`, `FEE_RECORDED`, `RECONCILIATION_ADJUSTED`, `RECONCILIATION_RECORDED`).
- Chưa có xác thực bên gọi (G12): **không** mở các endpoint này ra ngoài trước G12.
