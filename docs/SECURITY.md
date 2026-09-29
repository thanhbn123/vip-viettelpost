# Security rules

- Không commit `.env`.
- Không log password/token/Authorization header.
- Mask secret trong error reporting.
- Validate và authenticate webhook theo capability chính thức của provider.
- Store raw webhook event, nhưng loại bỏ/che thông tin nhạy cảm khi cần.
- Idempotency key/event fingerprint cho webhook.
- Least privilege cho shipping account.
- Rotate credentials theo quy trình vận hành.

---

## Webhook Viettel Post

**Nguồn hợp đồng:** <https://partner2.viettelpost.vn/document/webhook> (đối chiếu 29/09/2026).
**Mã nguồn:** `app/webhooks/` — `processor.py`, `viettel_post_payload.py`, `fingerprint.py`, `stores.py`, `routes.py`.
**Endpoint:** `POST /api/v1/shipping/webhooks/viettel-post`.

### Xác thực

- Tài liệu công bố trường **`TOKEN` trong body** (cùng cấp với `DATA`): *"Token bảo mật (Secret Key) do đối tác cung cấp"* để xác thực nguồn gốc webhook. Mã nguồn so `TOKEN` với `WEBHOOK_SHARED_SECRET` bằng `hmac.compare_digest` (so thời gian hằng).
- **Không có chữ ký/HMAC nào được tài liệu công bố → không tự bịa HMAC.** Toàn vẹn nội dung vì vậy **không** được bảo đảm bằng chữ ký; chỉ dựa vào TLS và bí mật dùng chung.
- Header `Authorization` có trong mẫu của tài liệu (giá trị dạng JWT) nhưng **không có quy trình kiểm tra được công bố** → không bắt buộc, không tin, không log.
- Chưa cấu hình `WEBHOOK_SHARED_SECRET` → **từ chối mọi request (503)**, không mở cửa khi thiếu cấu hình.
- Sai hoặc thiếu `TOKEN` → 401. Xác thực chạy **trước** kiểm tra idempotency và trước kiểm tra từng trường, để bên không có bí mật không dò được luật kiểm tra hay trạng thái trùng.

### Bí mật và log

- Không log `TOKEN`, bí mật cấu hình, header `Authorization`, hay body.
- Log chỉ gồm: loại kết quả, `provider_status`, canonical, 16 ký tự đầu của fingerprint. **Không** có tên người nhận, số điện thoại bưu tá, địa chỉ, vị trí.
- `TOKEN` không bao giờ được lưu: kho sự kiện chỉ nhận object `DATA`.
- Phản hồi ACK không lặp lại giá trị nào của payload.
- Bí mật thật chỉ nằm ở biến môi trường; test dùng chuỗi giả `test-webhook-secret-not-real`.

### Payload thô và PII

- `DATA` được lưu nguyên để kiểm toán, nhưng chứa PII (`RECEIVER_FULLNAME`, `EMPLOYEE_NAME`, `EMPLOYEE_PHONE`, `LOCATION_CURRENTLY`, có thể có link ảnh `POD`). Kho thật phải: giới hạn quyền đọc, có thời hạn lưu, không đưa vào log/metrics.
- Link ảnh `POD` chỉ tồn tại 6 tháng theo tài liệu; không coi là bằng chứng lâu dài.
- Không tin payload ngoài những trường đã kiểm: `ORDER_NUMBER` (chuỗi, không rỗng, ≤128 ký tự, không khoảng trắng/ký tự điều khiển), `ORDER_STATUS` (số nguyên không âm; chuỗi toàn chữ số cũng nhận). Các trường tiền (`MONEY_*`) **không** được dùng để quyết định gì trong pipeline này.

### Giới hạn và kiểm tra đầu vào

| Trường hợp | HTTP | Ghi chú |
|---|---|---|
| Body > 64 KiB (khai qua `Content-Length` hoặc đo thực tế) | 413 | Nên đặt thêm giới hạn ở reverse proxy |
| JSON hỏng / không giải mã UTF-8 | 400 | `MALFORMED_JSON` |
| Body không phải object, `DATA` không phải object | 400 | `INVALID_PAYLOAD` |
| Thiếu `DATA` / `ORDER_NUMBER` / `ORDER_STATUS` | 400 | `MISSING_FIELD` |
| `ORDER_NUMBER` sai định dạng | 400 | `INVALID_TRACKING_NUMBER` |
| `ORDER_STATUS` sai kiểu | 400 | `INVALID_STATUS_FORMAT` |
| Sai/thiếu `TOKEN` | 401 | `UNAUTHORIZED` |
| Chưa cấu hình bí mật | 503 | `NOT_CONFIGURED` |
| Mã trạng thái không biết | **200** | Lưu + đánh dấu xem xét, xem `STATUS_MAPPING.md` |
| Sự kiện trùng / phát lại | **200** | Không ghi lần hai |
| Kho lưu hỏng | 500 | Nhả khoá idempotency để lần thử lại của VTP được xử lý |

Kiểm tra `ORDER_NUMBER` dùng **danh sách đen** (khoảng trắng, ký tự điều khiển, độ dài) chứ không dùng danh sách trắng ký tự, vì tài liệu không công bố bảng chữ cái của mã vận đơn; danh sách trắng quên một ký tự hợp lệ sẽ làm mất sự kiện thật.

Tài liệu yêu cầu phản hồi **< 1 giây**; pipeline không gọi mạng. Kho thật cũng phải nhanh (ghi một dòng + khoá duy nhất).

### Idempotency

- VTP **không** công bố mã sự kiện trong payload, và nói rõ hành trình có thể **trùng/thừa**, thử lại **tối đa 5 lần** tới khi nhận HTTP 200.
- Fingerprint = SHA-256 của `VIETTEL_POST | ORDER_NUMBER | ORDER_STATUS | ORDER_STATUSDATE` (chuỗi ngày giữ nguyên, chỉ gộp khoảng trắng). Khoá idempotency = `VIETTEL_POST:<fingerprint>`.
- Cố ý **không** đưa vào fingerprint: `TOKEN`, `NOTE`, `STATUS_NAME`, vị trí, `MONEY_*`, thông tin bưu tá, `POD`, `REASON_CODE`, giờ nhận — các trường có thể khác nhau giữa hai lần gửi cùng một chuyển trạng thái.
- Thiếu `ORDER_STATUSDATE` → dự phòng: băm toàn bộ `DATA` đã chuẩn hoá (khoá sắp xếp), để hai lần cùng một mã trạng thái ở hai thời điểm không bị gộp nhầm.
- `IdempotencyStore.claim()` phải là **set-if-absent nguyên tử** (ví dụ `INSERT` trên cột `UNIQUE`). Bản in-memory hiện tại chỉ dùng cho test/dev: mất khi khởi động lại, không chia sẻ giữa nhiều worker → **chưa đủ cho staging/production**.

### Phát lại (replay)

- Không có chữ ký, nonce hay mốc thời gian ký → **không thể chống phát lại bằng mật mã**.
- Phát lại **y hệt** một sự kiện đã nhận → trùng fingerprint → ACK 200, không ghi lần hai, không đổi trạng thái.
- Kẻ có `TOKEN` vẫn giả được sự kiện **mới**. Giảm thiểu: chỉ nhận qua HTTPS, giữ bí mật mạnh và xoay vòng, đối soát định kỳ bằng API tra cứu đơn của VTP, cân nhắc giới hạn IP nếu VTP công bố dải IP (hiện **chưa** thấy công bố).
- **Không** từ chối theo tuổi sự kiện: tài liệu không nêu múi giờ `ORDER_STATUSDATE` hay khoảng thời gian thử lại, nên cửa sổ thời gian sẽ làm mất sự kiện thật.
- Sự kiện đến sau trạng thái cuối, hay đến sai thứ tự, vẫn được lưu và ACK; việc có đổi trạng thái đơn hay không thuộc tầng cập nhật đơn (cờ `is_terminal` có sẵn để dùng).
