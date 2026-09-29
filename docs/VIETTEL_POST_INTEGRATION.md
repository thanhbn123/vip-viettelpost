# Viettel Post integration

## Luồng dự kiến

1. Authenticate/get token.
2. Query service capability.
3. Calculate fee.
4. Create shipment.
5. Save provider tracking number.
6. Receive webhook.
7. Persist raw event.
8. Deduplicate.
9. Map provider status.
10. Update shipment + audit.

Bước 1–4 và hủy đơn do W-SHP-02 triển khai (`app/providers/viettel_post/`). Bước 5–10 thuộc worker khác.

## Nguồn chân lý

Chỉ dùng tài liệu Partner chính thức của Viettel Post, đọc ngày **2026-09-29**:

| Trang | URL |
|---|---|
| Hướng dẫn tích hợp | https://partner2.viettelpost.vn/document/detail-instructions |
| Môi trường và tham số chung | https://partner2.viettelpost.vn/document/environment-parameter |
| Token xác thực | https://partner2.viettelpost.vn/document/token-authen |
| Lấy danh sách dịch vụ (ID địa chỉ) | https://partner2.viettelpost.vn/document/get-list-service-by-address-id |
| Lấy danh sách dịch vụ (địa chỉ chi tiết) | https://partner2.viettelpost.vn/document/get-list-service-by-address-detail |
| Tính cước (ID địa chỉ) | https://partner2.viettelpost.vn/document/charges-id-address |
| Tạo đơn (ID địa chỉ) | https://partner2.viettelpost.vn/document/create-order-id-address |
| Cập nhật trạng thái vận đơn | https://partner2.viettelpost.vn/document/update-bill-of-lading-status |
| Cập nhật thông tin đơn hàng | https://partner2.viettelpost.vn/document/update-info-order |
| Lấy link in vận đơn | https://partner2.viettelpost.vn/document/sync-end-status |
| Webhook | https://partner2.viettelpost.vn/document/webhook |

Trang tài liệu ghi "Method & Resource Path: POST"; đường dẫn (path) lấy từ cURL mẫu trên chính trang đó.

## VERIFIED CONTRACT

### Môi trường

| Môi trường | Base URL |
|---|---|
| Development | `https://partnerdev.viettelpost.vn` |
| Production | `https://partner.viettelpost.vn` |

`ViettelPostClient(base_url=...)` nhận base URL; mặc định lấy `settings.vtp_base_url` (`VTP_BASE_URL`). Dev/test nên đặt `VTP_BASE_URL=https://partnerdev.viettelpost.vn`.

### Header chung (API cần xác thực)

| Header | Giá trị |
|---|---|
| `Token` | token xác thực — **không** phải `Authorization: Bearer` |
| `Content-Type` | `application/json;charset=UTF-8` |

### Phong bì phản hồi (envelope)

`{"status": <int>, "error": <bool>, "message": <string | list>, "data": <object | null>}`.
Thành công: `error: false`. Bị từ chối: `error: true`, `message` là thông báo (tài liệu mô tả dạng list).

Ngoại lệ đã thấy trong tài liệu: mẫu phản hồi `getPriceAll` là **mảng trần**, không có envelope.

### Xác thực

| Mục | Method | Path | Cần token | Request | Response |
|---|---|---|---|---|---|
| Login (token ngắn hạn) | POST | `/v2/user/Login` | Không | `USERNAME`, `PASSWORD` | `data.token`, `data.userId`, `data.partner`, `data.expired` |
| ownerconnect (token dài hạn / ủy quyền) | POST | `/v2/user/ownerconnect` | Có (`Token` = token bước Login) | `USERNAME`, `PASSWORD` | như trên |
| LoginVTP (đổi token bí mật từ viettelpost.vn) | POST | `/v2/user/LoginVTP` | Không | `token` | như trên |

- Token dài hạn từ `ownerconnect`: tài liệu ghi **thời hạn 1 năm**.
- Token ngắn hạn từ `Login`: tài liệu **không** nêu thời hạn.
- `data.expired` = `0` ở mọi mẫu, ý nghĩa không được mô tả → giữ nguyên trong `ViettelPostAuthResult.provider_expired_field`, không suy ra hạn.

`ViettelPostAuth.authenticate()`:
1. Có `VTP_TOKEN` → dùng nguyên token đó, không gọi mạng, không tự làm mới.
2. Không có → `Login` rồi `ownerconnect` bằng `VTP_USERNAME`/`VTP_PASSWORD`, giữ token trong bộ nhớ tiến trình.
3. Khi API trả một trong các thông báo lỗi token của bảng lỗi chính thức (`Header Token is required`, `Token invalid`, `Token invalid or expired`, `Invalid owner account or password!`) → `ViettelPostAuthError`. Provider xóa token đệm và thử lại **đúng một lần** nếu đang dùng username/password; với `VTP_TOKEN` tĩnh thì không thử lại.

### Endpoint nghiệp vụ đã triển khai

| Method adapter | Mục đích | Method | Path | Cần token | Nguồn |
|---|---|---|---|---|---|
| `get_services()` | Lấy dịch vụ chính + cộng thêm theo ID địa chỉ | POST | `/v2/order/getPriceAll` | Có | get-list-service-by-address-id |
| `calculate_fee()` | Tính cước theo ID địa chỉ | POST | `/v2/order/getPrice` | Có | charges-id-address |
| `create_shipment()` | Tạo đơn theo ID địa chỉ | POST | `/v2/order/createOrder` | Có | create-order-id-address |
| `cancel_shipment()` | Hủy đơn (`TYPE = 4`), chỉ áp dụng khi `ORDER_STATUS < 200` | POST | `/v2/order/UpdateOrder` | Có | update-bill-of-lading-status |

### Khóa payload của adapter (snake_case → Viettel Post)

Toàn bộ khóa Viettel Post nằm trong `app/providers/viettel_post/mapping.py`. Khóa lạ → `ValueError` (không bỏ qua im lặng). Thiếu khóa bắt buộc → `ValueError`.

Tuyến (bắt buộc ở cả ba API): `sender_province_id`, `sender_district_id`, `sender_ward_id`, `receiver_province_id`, `receiver_district_id`, `receiver_ward_id` → `SENDER_/RECEIVER_ PROVINCE|DISTRICT|WARD`. Hai khóa `*_district_id` phải có mặt nhưng được là `None` (mẫu tạo đơn chính thức gửi `SENDER_DISTRICT: null` cho địa chỉ 2 cấp).

Kiện hàng: `product_type` (`TH`/`HH`), `weight_grams`, `product_price`, `cod_amount` (→ `MONEY_COLLECTION`), `length_cm`, `width_cm`, `height_cm`.

- `get_services`: thêm `price_table_type` → `TYPE` (0 quốc tế, 1 trong nước). Bắt buộc: tuyến, `product_type`, `weight_grams`, `price_table_type`.
- `calculate_fee`: `price_table_type` → `NATIONAL_TYPE`; `service_code` → `ORDER_SERVICE`; `extra_service_codes` → `ORDER_SERVICE_ADD`. Bắt buộc: như trên + `service_code`.
- `create_shipment`: `order_number`, `sender_name|phone|address`, `receiver_name|phone|address`, `pickup_date`, `pickup_code`, `delivery_code`, `product_name`, `product_quantity`, `order_payment` (1–4), `service_code`, `extra_service_codes`, `note`, `items` (`name`, `quantity`, `price`, `weight_grams`), `return_address` (`required`, `full_address`, `province_id`, `district_id`, `ward_id`), `group_address_id`, `check_unique`, `extra_money`, `enable_sort_code`. Chuỗi > 150 byte UTF-8 → `ValueError` (tài liệu: "maxlength mặc định là 150 bytes").

Kết quả trả về (snake_case, không lộ khóa Viettel Post):
- `get_services` → list `{service_code, service_name, fee, delivery_time, exchange_weight_grams, extra_services[{code, name, description}]}`.
- `calculate_fee` → `{total, main_fee, fuel_fee, cod_fee, other_fee, vat, committed_delivery_time}`.
- `create_shipment` → `{tracking_number, cod_amount, total_fee, main_fee, fuel_fee, cod_fee, vat, committed_delivery_time, exchange_weight_grams, receiver_province_id, receiver_district_id, receiver_ward_id, sort_code}`.
- `cancel_shipment` → `{tracking_number, cancelled: True, message}`.

### Phân loại lỗi (`app/providers/viettel_post/errors.py`)

| Tình huống | Exception |
|---|---|
| Quá thời gian (timeout mặc định 20s, cấu hình được) | `ViettelPostTimeoutError` |
| Lỗi mạng trước khi có phản hồi | `ViettelPostNetworkError` |
| HTTP 4xx | `ViettelPostClientError` (`status_code`) |
| HTTP 5xx | `ViettelPostServerError` (`status_code`) |
| Envelope `error: true` | `ViettelPostBusinessError` (`provider_status`) |
| Envelope `error: true` với thông báo lỗi token | `ViettelPostAuthError` |
| Body không phải JSON, thiếu envelope, thiếu trường bắt buộc | `ViettelPostInvalidResponseError` |

Mọi thông điệp lỗi đi qua `redact()`: che token, username, password đã biết và mọi chuỗi dạng JWT (`eyJ...`), cắt còn 200 ký tự. Không đưa request body vào lỗi. `repr` của `ViettelPostAuth` và `ViettelPostAuthResult` không chứa credential.

## UNVERIFIED / TODO

| Mục | Trạng thái | Lý do |
|---|---|---|
| `get_shipment()` (tra cứu đơn) | `NotImplementedError` | Tài liệu Partner (2026-09-29) **không có** API tra cứu/hành trình đơn; hành trình đến qua webhook. Cần Viettel Post xác nhận contract chính thức. |
| `handle_webhook()` | Giữ nguyên scaffold | Ngoài phạm vi W-SHP-02. |
| Thời hạn token ngắn hạn (`Login`) | Không suy đoán | Tài liệu không nêu. |
| Ý nghĩa `data.expired` | Không diễn giải | Tài liệu không nêu. |
| Đơn vị `KPI_HT` ở tính cước | Giữ số thô | Trang tính cước chỉ ghi "Tổng thời gian giao hàng cam kết"; trang tạo đơn ghi "tính từ 24 giờ ngày nhận được đơn hàng", không nêu đơn vị. |
| `getPriceAll` trả envelope `error: false` | Coi là `ViettelPostInvalidResponseError` | Tài liệu chỉ mẫu mảng trần. Nếu API thật bọc envelope, cần sửa parser sau khi đo trên môi trường dev. |
| Biến thể "địa chỉ chi tiết" (`/v2/order/getPriceAllNlp`, tạo đơn bằng địa chỉ chi tiết) | Chưa triển khai | Đã đọc trang dịch vụ; chưa cần cho phạm vi này. |
| `/v2/order/edit`, TYPE 1/2/3/5 của `UpdateOrder`, `/v2/order/printing-code` | Chưa triển khai | Không thuộc method của `ShippingProvider`. |
| `VERIFICATION_CODE` (tạo đơn, dịch vụ PTTX) | Không hỗ trợ (khóa lạ → lỗi) | Chứa dữ liệu định danh người nhận; cần quyết định riêng về bảo mật. |
| Header `Cookie: SERVERID=...` trong cURL mẫu | Không gửi | Không nằm trong bảng header bắt buộc của trang "Môi trường và tham số chung". |
| Gọi thử thật trên `partnerdev` | Chưa làm | Không có credential test; mọi test dùng mock HTTP. |

## Type drift với W-SHP-01 (PR #1, HEAD `8515be2e8a351cec548d530173503e8ee21e7a34`)

Nhánh này xuất phát từ baseline `3b89b36` và giữ contract `dict` của baseline. PR #1 đổi `ShippingProvider` sang DTO có kiểu (`app/providers/base/dto.py`). Integration Worker cần nối:

| Method | Baseline (nhánh này) | PR #1 |
|---|---|---|
| `authenticate` | `-> str` (token) | `-> AuthResult(provider, authenticated, expires_at)` — không mang token |
| `get_services` | `dict -> list[dict]` | `ServiceQuery -> list[ServiceOption]` |
| `calculate_fee` | `dict -> dict` | `FeeRequest -> FeeQuote` |
| `create_shipment` | `dict -> dict` | `CreateShipmentRequest -> CreateShipmentResult` |
| `get_shipment` | `-> dict` | `-> ShipmentSnapshot` |
| `cancel_shipment` | `-> dict` | `-> CancelShipmentResult` (cần `status`) |
| `handle_webhook` | `dict -> dict` | `WebhookRequest -> WebhookResult` |
| `code` | `"VIETTEL_POST"` (str) | `ClassVar[ShippingProviderCode]` |

Điểm cần quyết khi nối:
1. **Địa chỉ**: `Address` của PR #1 có `ward`/`district`/`province` dạng **chuỗi tên**; ba API đã triển khai cần **ID số** (`SENDER_PROVINCE`...). Cần lớp tra ID (danh mục địa danh V2/V3) hoặc chuyển sang biến thể "địa chỉ chi tiết".
2. **Kiện hàng**: PR #1 có `packages: list[ShipmentPackage]` (≥1); Viettel Post nhận một tổng trọng lượng/kích thước + `LIST_ITEM`.
3. **Tiền**: PR #1 dùng `Money(Decimal, currency)`; Viettel Post trả số nguyên VND.
4. **Trường Viettel Post bắt buộc không có trong DTO**: `product_type`, `price_table_type`, `order_payment`, `service_code` (bắt buộc ở tính cước/tạo đơn nhưng `str | None` trong DTO).
5. **Trạng thái sau tạo/hủy**: DTO đòi `ShipmentStatus`; việc đó thuộc status mapper (worker khác).
6. Cách nối đề xuất: giữ `mapping.py` làm lớp dịch dict ↔ Viettel Post, thêm một lớp mỏng DTO ↔ dict trong provider; token vẫn chỉ nằm trong adapter.
