# Quan sát & chịu lỗi (G11)

## Endpoint

| Path | Dùng cho | Ghi chú |
|---|---|---|
| `GET /health` | Liveness | Tiến trình còn trả lời |
| `GET /health/ready` | Readiness | 200/503. Kiểm: kết nối CSDL, revision Alembic = head của mã, có bí mật webhook, có credential nhà vận chuyển (chỉ **có/không**, không bao giờ trả giá trị). **Không** gọi Viettel Post |
| `GET /metrics` | Số đo trong tiến trình (JSON) | Bộ đếm + thời lượng (số lần, trung bình, lớn nhất) theo nhãn; đặt sau xác thực ở G12 |

## Nhật ký

- Mỗi dòng mang `request_id` (header `X-Request-ID`, hoặc sinh mới).
- `LOG_FORMAT=json` cho log có cấu trúc (`time`, `level`, `logger`, `request_id`, `message`); mặc định `text`. `LOG_LEVEL` mặc định `INFO`.
- Lưới an toàn che bí mật: chuỗi dạng JWT và mọi giá trị bí mật đã cấu hình (`VTP_PASSWORD`, `VTP_TOKEN`, `WEBHOOK_SHARED_SECRET`) bị thay bằng `***` trước khi ghi. Mã vẫn không được log bí mật — đây chỉ là lớp thứ hai.
- Cuộc gọi nhà vận chuyển: `provider_call provider=… op=… attempt=… outcome=… duration_ms=…`; thử lại: `provider_retry …`.
- Webhook: số đếm `webhook_events{provider,result}` và thời lượng `webhook_processing_seconds`.

## Thử lại (D-031)

| Thao tác | Thử lại? | Lý do |
|---|---|---|
| `authenticate`, `get_services`, `calculate_fee`, `get_shipment` | Có, khi timeout / mạng / 5xx; tối đa `PROVIDER_RETRY_MAX_ATTEMPTS` (3) lần, lùi mũ từ `PROVIDER_RETRY_BASE_DELAY` (0,2 s) tới trần `PROVIDER_RETRY_MAX_DELAY` (2 s) | Không đổi gì ở hãng |
| `create_shipment`, `cancel_shipment` | **Không bao giờ** tự thử lại | Sau timeout kết quả không rõ; thử mù có thể tạo/huỷ hai lần (D-023, D-028) |
| Bị từ chối, lỗi xác thực, phản hồi lạ | Không | Thử lại không đổi kết quả |

Timeout mỗi yêu cầu: `VTP_TIMEOUT_SECONDS` (20 s). Không có vòng thử vô hạn.

## Việc định kỳ cần giám sát

- `python -m app.jobs.replay_webhooks` (idempotent) — áp sự kiện đến trước vận đơn / `FAILED` sau khi hết lượt thử của hãng.
- Thước đo `unmatched_with_shipment()` phải về 0 sau mỗi lần chạy.
- `GET /api/v1/shipping/shipments?requires_review=true` và `?status=READY_TO_CREATE` là hai hàng đợi cho người vận hành.

Giới hạn còn lại: số đo nằm trong bộ nhớ một tiến trình (mất khi khởi động lại, không gộp nhiều worker); xuất sang hệ đo chuyên dụng là việc sau. Handler async gọi CSDL đồng bộ (ảnh hưởng thông lượng, verifier PR #8 LOW-6) — chấp nhận ở quy mô hiện tại.
