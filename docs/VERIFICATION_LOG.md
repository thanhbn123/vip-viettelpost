# VERIFICATION LOG — verifier độc lập theo từng PR

Mỗi PR được một tác tử verifier **không viết mã đó** kiểm trên bản clone riêng, chỉ đọc, trước khi merge. Ghi: HEAD được kiểm, số test đo được, phát hiện, cách xử lý, kết luận.

## PR #6 — G05 Integration foundation

- Lần 1, HEAD `bcf34cf`: 287 passed (SQLite); 344 passed / 1 skipped (SQLite + PG 16). **FAIL**: 2 HIGH (race retry `FAILED` áp hai lần; `_record_failure` ghi đè lần giao thành công) + 1 MEDIUM (SQLite batch migration làm rỗng FK). Xử lý: D-020, D-021 (chi tiết `INTEGRATION_NOTES.md`).
- Lần 2, HEAD `20f32b4`: 290 passed; 350 passed / 1 skipped. **PASS**. 2 LOW mới ở `migrations/env.py` → sửa ở PR #8.

## PR #8 — G06 Application service / REST API

- Lần 1, HEAD `2c02b53`: 317 passed (SQLite); 401 passed / 1 skipped (PG riêng). **PASS**, kèm:

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | MEDIUM | Hai lệnh huỷ đồng thời gọi hãng hai lần | D-028: claim `operation_lock` bằng UPDATE có điều kiện → lệnh thứ hai 409 `operation_in_progress` |
| 2 | MEDIUM | Huỷ ghi đè `DELIVERED` do webhook đặt trong lúc gọi hãng (và giải phóng đơn) | D-028: ghi cuối có điều kiện `status = trạng thái đã đọc`; xung đột → giữ trạng thái, audit `PROVIDER_CANCELLED_AFTER_STATUS_CHANGE`, 409 |
| 3 | LOW | HTTP 401/403 của VTP bị coi là lỗi của bên gọi (422) | `ViettelPostHTTPAuthError` → 502 `provider_auth_failed` |
| 4 | LOW | Mọi `IntegrityError` lúc giữ chỗ bị báo trùng đơn | Chỉ index `uq_shipments_active_provider_order` mới là 409 |
| 5 | LOW | Phí lúc tạo không kiểm đơn vị tiền | Khác đơn vị → không lưu, log cảnh báo |
| 6 | LOW | Gọi CSDL đồng bộ trong handler async | Chấp nhận (chỉ ảnh hưởng thông lượng); xem G11 |
| 7 | LOW | Lỗi bất ngờ trả 500 thô | Handler chung: JSON `internal_error` + `request_id`, không lộ chi tiết |

Test hồi quy #1 và #2 **hỏng trên mã cũ** (2 failed) và đạt trên mã sửa.
