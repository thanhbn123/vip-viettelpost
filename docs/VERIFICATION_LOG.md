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

- Lần 2, HEAD `1bf3302`: 325 passed; 414 passed / 1 skipped (PG riêng). **PASS** → merge PR #8 (`051e535`). Còn lại, sửa ở PR G07:

| # | Mức | Phát hiện | Xử lý (PR G07) |
|---|---|---|---|
| 1 | MEDIUM | Hãng đã nhận huỷ nhưng ghi CSDL hỏng → 500 chung, không audit, không log rõ | `PersistenceAfterProviderError` + log ERROR kèm mã vận đơn + audit `PROVIDER_CANCEL_NOT_RECORDED`; giữ khoá (không gửi huỷ lần hai ngay); webhook huỷ của VTP vẫn đưa vận đơn về `CANCELLED` |
| 2 | LOW | `asyncio.CancelledError` giữa lúc gọi hãng không nhả khoá | Bắt `BaseException` để nhả khoá rồi ném lại |
| 3 | LOW | Giá trị khoá luôn là `"CANCEL"` | Token riêng mỗi yêu cầu `CANCEL:<16 hex>`; ghi cuối so đúng token |
| 4 | LOW | Phản hồi 500 thiếu header `X-Request-ID` | Handler 500 tự đặt header |
| 5 | (ghi chú) | Downgrade về `base` trên PG hỏng FK khi đã có vận đơn | Đúng thiết kế: downgrade về base chỉ cho CSDL rỗng (dev/test); ghi vào rollback trong `DATABASE_SCHEMA.md` |

## PR #10 — G07 Durable webhook processing

- Lần 1, HEAD `fba138b`: 340 passed (SQLite); 444 passed / 1 skipped (PG riêng). Race thử thêm của verifier (5 sự kiện khác nhau đồng thời × 8 vận đơn; tạo + 2 job replay + 2 webhook đồng thời, mỗi thứ 3 lần, cả hai CSDL): sạch. **PASS**, kèm:

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| F1 | MEDIUM | Khoá so thứ tự hai loại (có múi giờ / chữ VTP) không bao giờ so với nhau → bật `VTP_WEBHOOK_TIMEZONE` sau đó thì sự kiện cũ kéo lùi trạng thái | Hãng có hàm khoá riêng (VTP) luôn so bằng khoá đó |
| F2 | MEDIUM | Khe hở D-027 chỉ job replay cứu được; job chưa có lịch | Thêm thước đo `unmatched_with_shipment` (phải về 0 sau mỗi lần chạy); lịch chạy là việc G14 |
| F3 | MEDIUM | Job replay bỏ qua dòng `FAILED` → mất sự kiện khi CSDL hỏng lâu hơn 5 lần thử của VTP | Job và `replay_unmatched` nhận cả `FAILED` |
| F4 | LOW | Huỷ: timeout/5xx/huỷ yêu cầu vẫn nhả khoá → gửi huỷ lần hai ngay | Chỉ nhả khi hãng từ chối; kết quả không rõ giữ khoá tới hết hạn, audit `PROVIDER_CANCEL_OUTCOME_UNKNOWN` |
| F5 | LOW | Webhook huỷ của VTP tới giữa lúc gọi huỷ → báo xung đột giả | Trạng thái đã `CANCELLED` = đồng thuận: 200 |
| F6 | LOW | `processed_at` ghi giờ nhận gốc khi replay | Ghi giờ xử lý thật |
| F7 | LOW | Đọc toàn bộ sự kiện cũ mỗi lần (O(n)) | Chấp nhận ở quy mô hiện tại |

Test F1 và F3 **hỏng trên mã cũ** (2 failed) và đạt trên mã sửa.
- Lần 2, HEAD `f635fa2`: 344 passed; 452 passed / 1 skipped. 60 phép thử race (retry `FAILED` trực tiếp × job replay, cả hai CSDL): mỗi sự kiện áp đúng 1 lần. **PASS** → merge PR #10 (`0fbdc2d`). Còn LOW L1 (job dừng cả lượt khi một khoá lỗi), L2 (replay trong luồng tạo không cô lập), L3 (thước đo bỏ sót `FAILED`/`RECEIVED`) → sửa ở PR G09, có test.
