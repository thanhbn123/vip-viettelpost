# INTEGRATION NOTES — CR-SHP-001

## G05 — Integration Foundation (`integration/cr-shp-001`)

Đo lúc bắt đầu (2026-09-29 12:3x +07, `git fetch --all --prune`): `origin/main` = `origin/develop` = `3b89b367cf3bd57ac6021645ff15ae37958898f7`. Bốn PR đều OPEN, base `develop`, MERGEABLE, CI `test` SUCCESS, 0 review.

| PR | Nhánh | HEAD | Tests của nhánh |
|---|---|---|---|
| #1 | `feature/shp-core-domain` | `8515be2e8a351cec548d530173503e8ee21e7a34` | 63 passed |
| #4 | `feature/shp-database` | `4df8ce7b699bf02890ed831c1383e11eb153aef5` | 49 passed |
| #2 | `feature/vtp-api-client` | `d83ae97a2c0acc0f1e4f4789e8d2821b81f6da43` | 51 passed |
| #3 | `feature/vtp-webhook-status` | `a45b7fd6b692b4efa3093b275d83011c4de12ebf` | 80 passed |

### Thứ tự và kết quả merge (D-001)

| Bước | Merge | Xung đột văn bản | `pytest -q` sau bước |
|---|---|---|---|
| 1 | PR #1 core/domain | 0 | 63 passed |
| 2 | PR #4 database | 0 | 110 passed |
| 3 | PR #2 VTP client | 0 | 159 passed |
| 4 | PR #3 webhook/status | 0 | 237 passed |

"0 xung đột" ở đây là **xung đột văn bản do `git merge` báo** (không file nào ở trạng thái `U`). Lệch hợp đồng/kiểu (drift) không hiện thành xung đột văn bản — chúng được xử lý ở các commit hoà giải bên dưới. Nhánh worker gốc **không bị sửa**.

### Drift đã hoà giải

| # | Drift (nguồn) | Cách xử | Quyết định | Test |
|---|---|---|---|---|
| 1 | `ViettelPostProvider` dùng chữ ký `dict` trong khi PR #1 đổi `ShippingProvider` sang DTO typed (#1↔#2) | Tách `ViettelPostApi` (dict nội bộ) + `ViettelPostProvider` typed | D-017 | `test_vtp_api.py` (bộ test HTTP/auth gốc của #2), `test_vtp_provider_typed.py` |
| 2 | `Address` tên vs ID số VTP (#1↔#2) | `provider_options.sender_location/receiver_location` | D-002, D-003 | `test_get_services_maps_ids_total_weight_and_money` |
| 3 | `packages[]` vs một tổng trọng lượng + `LIST_ITEM` (#1↔#2) | Cộng khối lượng; kích thước chỉ khi 1 kiện; items từ options | D-004 | `test_get_services_...`, `test_create_shipment_items_from_options` |
| 4 | `Money(Decimal)` vs số nguyên VND (#1↔#2) | `to_vnd` / `from_vnd`; từ chối khác VND hoặc có số lẻ | D-007 | `test_money_to_vnd_rules` |
| 5 | Trường VTP bắt buộc không có trong DTO: `product_type`, `price_table_type`, `order_payment`, `service_code` (#1↔#2) | `ViettelPostOptions`; `service_code` và `order_payment` thiếu → lỗi trước khi gọi mạng | D-010 | `test_create_shipment_rejects_bad_options_before_network`, `test_calculate_fee_requires_service_code_before_network` |
| 6 | `authenticate() -> str` (token) vs `AuthResult` không mang token (#1↔#2) | Trả `AuthResult(authenticated=True, expires_at=None)`; token ở lại adapter | — | `test_authenticate_returns_result_without_token` |
| 7 | Trạng thái sau tạo/huỷ (#2↔#1/#3) | `createOrder` thành công → `CREATED`; huỷ thành công → `CANCELLED` | — | `test_create_shipment_typed_mapping`, `test_cancel_typed` |
| 8 | `ShipmentEvent.status` bắt buộc vs mã lạ không có canonical (#1↔#3) | `status` Optional + `requires_review` + validator | D-005 | `test_event_without_status_requires_review_and_provider_status`, `test_apply_event_without_status_...` |
| 9 | `occurred_at` aware vs giờ VTP không múi giờ (#1↔#3) | `occurred_at` Optional + `occurred_at_raw` + `received_at`; `VTP_WEBHOOK_TIMEZONE` | D-006 | `test_handle_webhook_mapped_status_without_timezone_keeps_raw_time`, `test_configured_timezone_gives_aware_time` |
| 10 | `provider` enum vs chuỗi (#1↔#3) | `ViettelPostProvider.code` là `ShippingProviderCode`; sự kiện dùng enum | — | `test_adapter_implements_typed_contract` |
| 11 | `handle_webhook(dict) -> dict` vs `WebhookRequest -> WebhookResult` (#1↔#2↔#3) | Adapter parse không trạng thái, dùng chung parser/mapper của #3 | D-018 | `test_handle_webhook_*` |
| 12 | Kho chống trùng in-memory (#3) vs bảng `shipping_webhook_events` (#4) | `SqlWebhookSink` (một transaction/lần giao) | D-011 | `tests/integration/test_webhook_persistence.py` (gồm 8 luồng giao trùng đồng thời) |
| 13 | `provider` enum vs `provider_id` (#1↔#4) | Tra `shipping_providers.code`; migration gieo `VIETTEL_POST` | D-012 | `test_shp_0002_seeds_viettel_post` |
| 14 | `Money` vs cột tiền + một `currency`/dòng (#1↔#4) | `mappers.single_currency` từ chối vận đơn nhiều đơn vị tiền | — | `test_mixed_currency_shipment_is_rejected` |
| 15 | COD `None` vs `0` (#1↔#4) | `None ↔ 0` | D-008 | `test_no_cod_maps_to_zero_and_back_to_none`, `test_cod_round_trip` |
| 16 | `fee` domain vs `estimated_fee/actual_fee` (#1↔#4) | actual nếu có, không thì estimate | D-009 | `test_no_cod_maps_to_zero_and_back_to_none` |
| 17 | `ShipmentEvent` domain ↔ bản ghi (#1↔#4) | `mappers.new_event_from_domain` / `event_to_domain` | D-005 | `test_review_event_round_trip` |
| 18 | `shipment_events.canonical_status` NOT NULL, `occurred_at` NOT NULL (#4) vs mã lạ / giờ không múi (#3) | Migration `shp_0002` | D-005, D-006, D-015 | `test_shp_0002_*` |
| 19 | Độ chính xác `Money` (#1) vs `NUMERIC(18,2)` (#4) | Giới hạn trong domain | D-007 | `test_money_rejects_precision_beyond_storage` |
| 20 | `ShippingService`/`container` baseline dùng `dict` | Service typed + `UnsupportedProviderError`; route tạm typed (API đầy đủ ở G06) | — | toàn bộ suite |

### Thay đổi phụ kèm theo

- `VTP_BASE_URL` mặc định = môi trường development (D-013).
- `.gitignore` chặn `*.db` (DATABASE_URL mặc định là SQLite ở gốc repo).
- `requirements.txt` thêm `psycopg[binary]==3.2.3` (driver PostgreSQL — mục tiêu chạy thật).
- `pyproject.toml`: `asyncio_default_fixture_loop_scope = "function"` (bỏ cảnh báo pytest-asyncio).
- Route webhook chạy processor trong threadpool (I/O CSDL chặn).
- SQLite `BEGIN IMMEDIATE` (D-014).
- CI thêm job `postgres` (D-016).

### Chưa làm trong G05 (có chủ đích)

- Áp sự kiện webhook vào vận đơn (cập nhật `shipments`, nối `shipment_events`, audit) → **G07**. Hiện sự kiện được lưu bền ở trạng thái `RECEIVED`.
- API ứng dụng trung lập với hãng (quote, tạo/tra/huỷ có lưu CSDL) → **G06**.
- Tra ID địa danh VTP theo tên → rủi ro R-006.
