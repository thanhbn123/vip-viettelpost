# Xử lý webhook bền (G07)

Luồng cho mỗi lần Viettel Post gọi `POST /api/v1/shipping/webhooks/viettel-post`:

1. Giới hạn kích thước (`WEBHOOK_MAX_BODY_BYTES`) → giải mã JSON → kiểm `TOKEN` (so sánh hằng thời gian; chưa cấu hình bí mật → 503, fail closed) → kiểm trường bắt buộc → dấu vân tay (fingerprint) → ánh xạ trạng thái (`STATUS_MAPPING.md`).
2. **Một transaction CSDL** (`SqlWebhookSink`):
   - `INSERT` vào `shipping_webhook_events` — UNIQUE `(provider_id, fingerprint)` là phép claim nguyên tử; dòng `FAILED` chỉ được claim lại bằng `UPDATE` có điều kiện (D-011, D-020). Payload lưu là `DATA`, **không có `TOKEN`**.
   - `WebhookShipmentApplier`: tìm vận đơn theo `(provider_id, tracking_number)` (khoá dòng), nối `shipment_events` (khử trùng theo fingerprint), đổi trạng thái vận đơn nếu được phép, ghi audit `STATUS_CHANGED_BY_PROVIDER` (actor `WEBHOOK`), đặt dòng webhook `PROCESSED`.
3. Commit → ACK HTTP 200. Lỗi bất kỳ → rollback toàn bộ, ghi `FAILED` ở transaction riêng, trả 5xx để VTP gửi lại (tối đa 5 lần theo tài liệu VTP).

## Luật đổi trạng thái (D-026)

| Tình huống | Sự kiện | Trạng thái vận đơn | Cần xem xét tay |
|---|---|---|---|
| Có canonical, mới hơn mọi sự kiện đã áp | ghi | đổi | không |
| Mã lạ / đã biết nhưng không canonical | ghi | giữ | **có** |
| Canonical trùng trạng thái hiện tại (vd. VTP xác nhận lệnh huỷ của ta) | ghi | giữ | không |
| Vận đơn đã ở trạng thái cuối (`DELIVERED`, `RETURNED`, `CANCELLED`) | ghi, `decision=AFTER_TERMINAL_STATUS` | giữ | **có** |
| Cũ hơn sự kiện đã áp (đến trễ) | ghi, `decision=OUT_OF_ORDER` | giữ | **có** |
| Chưa có vận đơn với mã đó | không | — | dòng webhook `IGNORED/SHIPMENT_NOT_FOUND` |

So thời gian: với VTP **luôn** so chữ `ORDER_STATUSDATE` đã phân tích (mọi sự kiện VTP chung một múi giờ nên so với nhau là hợp lệ), kể cả khi đã cấu hình `VTP_WEBHOOK_TIMEZONE` — để bật múi giờ về sau không làm sự kiện cũ và mới trở nên không so được (verifier PR #10, F1). Hãng không có hàm khoá riêng thì dùng `occurred_at` có múi giờ. Không phân tích được thì áp theo thứ tự đến.

## Sự kiện đến trước vận đơn (D-027)

VTP có thể gọi lại trước khi luồng tạo vận đơn ghi xong mã vận đơn. Sự kiện đó được lưu `IGNORED/SHIPMENT_NOT_FOUND` và:
- được áp ngay khi luồng tạo ghi mã vận đơn (`replay_unmatched` trong cùng transaction);
- còn một khe hở nhỏ (transaction webhook đọc bảng vận đơn ngay trước khi luồng tạo commit) → chạy định kỳ `python -m app.jobs.replay_webhooks` (idempotent). Job cũng nhận các dòng `FAILED` (hết 5 lần thử của VTP). Lịch chạy là việc của staging (G14).
- Giám sát: `app.jobs.replay_webhooks.unmatched_with_shipment()` đếm dòng `IGNORED/SHIPMENT_NOT_FOUND` mà vận đơn nay đã có — phải về 0 sau mỗi lần chạy job.
