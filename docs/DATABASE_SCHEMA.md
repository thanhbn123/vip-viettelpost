# DATABASE_SCHEMA — VIP Shipping Gateway

CR-SHP-001 · Worker W-SHP-04 · Migration `shp_0001_shipping_gateway`

Tài liệu này mô tả persistence layer (tầng lưu trữ) của gateway vận chuyển:
10 bảng, ràng buộc, index, cách lưu tiền, chính sách bí mật, quy trình migration
và điểm cần khớp với domain model (mô hình nghiệp vụ) của W-SHP-01.

## 1. Stack đã đo

| Hạng mục | Giá trị | Nguồn |
|---|---|---|
| SQLAlchemy | 2.0.36, **sync** (đồng bộ) | `requirements.txt` |
| Alembic | 1.14.0 — trước lượt này chưa cấu hình; nay đặt trọn trong `migrations/` | `requirements.txt` |
| DB đích | PostgreSQL (đã chạy thử trên PostgreSQL 16.15) | xem mục 9 |
| DB kiểm thử / dev | SQLite (mặc định `DATABASE_URL=sqlite:///./vip_shipping.db`) | `app/core/config.py` |
| Naming convention (quy ước đặt tên) | `ix_/uq_/ck_/fk_/pk_` + tên bảng + cột | `app/db/base.py` |

Không đổi stack. Không thêm driver PostgreSQL vào `requirements.txt` (ngoài phạm vi W-SHP-04).

## 2. Bảng

| Bảng | Vai trò | Xoá |
|---|---|---|
| `shipping_providers` | Danh mục hãng vận chuyển. `code` UNIQUE, viết HOA; không giới hạn trong danh sách cứng | RESTRICT từ mọi bảng con |
| `shipping_accounts` | Tài khoản tại một hãng. Chỉ giữ **tham chiếu** bí mật | RESTRICT |
| `shipments` | Vận đơn: đơn hàng, hãng, tài khoản, mã vận đơn, trạng thái, người gửi/nhận, COD, phí | RESTRICT khi còn lịch sử/tài chính |
| `shipment_packages` | Kiện hàng của vận đơn | **CASCADE** theo vận đơn |
| `shipment_events` | Lịch sử trạng thái đã chuẩn hoá, **chỉ ghi thêm** | RESTRICT |
| `shipment_fees` | Dòng phí chi tiết: ước tính / hãng tính thật / điều chỉnh | RESTRICT |
| `shipment_cod` | Vòng đời COD (tiền thu hộ): kỳ vọng → hãng đã thu → đã chuyển về | RESTRICT |
| `shipment_reconciliation` | Mỗi lần đối soát kỳ vọng với thực tế (COD hoặc phí) theo bảng kê của hãng | RESTRICT |
| `shipping_webhook_events` | Webhook thô, lưu trước khi xử lý: chống trùng, phát lại, gỡ lỗi | SET NULL ở `shipment_events.webhook_event_id` |
| `shipping_audit_logs` | Nhật ký thay đổi quan trọng. Không có FK, sống lâu hơn thực thể | không phụ thuộc |

Cả 10 bảng trong đề bài đều được tạo. Không gộp bảng nào.

### 2.1 Cột chính

**`shipping_providers`**: `id`, `code` (≤32, UNIQUE, `code = upper(code)`), `name`, `enabled`, `created_at`, `updated_at`.

**`shipping_accounts`**: `id`, `provider_id` → providers, `account_name` (UNIQUE theo hãng), `external_account_id`, `secret_reference` (dạng `scheme://…`), `enabled`, `metadata_json`, `created_at`, `updated_at`.

**`shipments`**: `id`, `order_id`, `provider_id`, `shipping_account_id` (nullable), `tracking_number` (nullable khi còn DRAFT), `service_code`, `status` (CHECK theo 12 trạng thái chuẩn), `provider_status` (chuỗi gốc của hãng, chỉ để tra), `sender_*` và `receiver_*` (name, phone, address_line, ward, district, province), `package_count`, `cod_amount`, `currency`, `estimated_fee`, `actual_fee`, `created_at`, `updated_at`, `created_by`.

Địa chỉ để **dạng cột phẳng**, không tách bảng: V1 mỗi vận đơn đúng một người gửi, một người nhận, khớp `Address` của domain. Tách bảng địa chỉ để dùng lại là việc về sau.

**`shipment_packages`**: `id`, `shipment_id`, `package_index` (≥1, UNIQUE theo vận đơn), `weight_grams` (>0), `length_cm`/`width_cm`/`height_cm` (NULL hoặc >0), `description`, `declared_value`, `created_at`.

**`shipment_events`**: `id`, `shipment_id`, `provider_id`, `canonical_status`, `provider_status`, `provider_event_id`, `description`, `location`, `occurred_at`, `received_at`, `webhook_event_id` (tham chiếu tới webhook thô), `metadata_json`.

**`shipment_fees`**: `id`, `shipment_id`, `fee_type`, `source` ∈ {ESTIMATE, PROVIDER_ACTUAL, ADJUSTMENT}, `amount` (≥0, riêng ADJUSTMENT được âm), `currency`, `provider_reference`, `note`, `created_at`, `created_by`.

**`shipment_cod`**: một dòng mỗi vận đơn (`shipment_id` UNIQUE). `expected_amount`, `collected_amount`, `remitted_amount`, `currency`, `status` ∈ {PENDING, COLLECTED, REMITTED, PARTIAL, FAILED, CANCELLED}, `collected_at`, `remitted_at`, `remittance_reference`.

**`shipment_reconciliation`**: `shipment_id`, `provider_id`, `kind` ∈ {COD, FEE}, `statement_reference` (mã bảng kê của hãng), `expected_amount`, `actual_amount`, `difference_amount` (CHECK `= actual - expected`), `currency`, `status` ∈ {PENDING, MATCHED, MISMATCH, RESOLVED}, `reconciled_at`, `note`, `created_by`.

**`shipping_webhook_events`**: `provider_id`, `event_id`, `fingerprint` (SHA-256 hex, dài đúng 64), `tracking_number`, `order_id`, `payload_json`, `headers_json`, `received_at`, `processed_at`, `processing_status` ∈ {RECEIVED, PROCESSING, PROCESSED, FAILED, IGNORED}, `attempt_count`, `error_code`, `error_message`.

**`shipping_audit_logs`**: `entity_type`, `entity_id`, `action`, `actor_type` ∈ {USER, SYSTEM, PROVIDER, WEBHOOK}, `actor_id`, `before_json`, `after_json`, `reason`, `request_id`, `created_at`.
Action (hành động) dùng ở tầng repository: `SHIPMENT_CREATED`, `SHIPMENT_CANCELLED`, `COD_CHANGED`, `PROVIDER_CHANGED`, `ACCOUNT_CHANGED`, `MANUAL_STATUS_OVERRIDE`, `RECONCILIATION_ADJUSTED`. DB chỉ CHECK `action <> ''`, để thêm hành động mới không cần migration.

## 3. Quan hệ và chiến lược xoá

```
shipping_providers ─┬─< shipping_accounts
                    ├─< shipments ─┬─< shipment_packages      (CASCADE)
                    │              ├─< shipment_events        (RESTRICT, FK kép)
                    │              ├─< shipment_fees          (RESTRICT)
                    │              ├── shipment_cod           (RESTRICT, 1-1)
                    │              └─< shipment_reconciliation(RESTRICT, FK kép)
                    └─< shipping_webhook_events ──< shipment_events.webhook_event_id (SET NULL)
shipping_audit_logs  (không FK)
```

- **Mặc định RESTRICT**: không xoá được hãng còn vận đơn, không xoá được vận đơn còn lịch sử, COD, phí hay đối soát. Lịch sử vận đơn không thể mất vì một lệnh xoá nhầm.
- **CASCADE chỉ cho kiện hàng**: kiện là một phần của vận đơn. Một bản nháp chưa có lịch sử xoá đi thì kiện đi theo.
- **SET NULL cho liên kết webhook**: dọn webhook thô cũ không kéo mất sự kiện đã chuẩn hoá.
- **Audit không có FK**: nhật ký còn nguyên khi thực thể bị xoá.
- **FK kép** `(shipment_id, provider_id) → shipments(id, provider_id)` ở `shipment_events` và `shipment_reconciliation`, và `(shipping_account_id, provider_id) → shipping_accounts(id, provider_id)` ở `shipments`: DB tự chặn sự kiện của hãng A gắn vào vận đơn hãng B, hay tài khoản GHN gắn vào vận đơn VTP. Cần thêm hai UNIQUE `(id, provider_id)` làm đích FK.

## 4. Ràng buộc UNIQUE

| Ràng buộc | Mục đích |
|---|---|
| `uq_shipping_providers_code` | mã hãng duy nhất |
| `uq_shipping_accounts_provider_id_account_name` | tên tài khoản duy nhất trong một hãng |
| `uq_shipments_provider_id_tracking_number` | mã vận đơn duy nhất **theo hãng** (hai hãng có thể trùng số) |
| `uq_shipment_packages_shipment_id_package_index` | thứ tự kiện không trùng |
| `uq_shipment_events_provider_id_provider_event_id` | chống ghi trùng sự kiện khi hãng có mã sự kiện |
| `uq_shipment_cod_shipment_id` | một dòng COD mỗi vận đơn |
| `uq_shipping_webhook_events_provider_id_fingerprint` | chống trùng webhook theo dấu vân tay nội dung |
| `uq_shipping_webhook_events_provider_id_event_id` | chống trùng webhook khi hãng gửi mã sự kiện |
| `uq_shipments_id_provider_id`, `uq_shipping_accounts_id_provider_id` | đích cho FK kép |

**NULL trong UNIQUE**: cả SQLite và PostgreSQL đều coi NULL là khác nhau. Vì vậy nhiều vận đơn DRAFT chưa có `tracking_number`, nhiều sự kiện không có `provider_event_id`, nhiều webhook không có `event_id` cùng tồn tại được. Đã kiểm trên cả hai: `test_null_tracking_allows_many_drafts`, `test_webhook_event_id_unique_but_nullable`, `test_events_without_provider_event_id_are_all_kept` (SQLite), và bản chạy thử PostgreSQL ở mục 9.
Vì chống trùng dựa vào `event_id` chỉ có hiệu lực khi hãng gửi mã, `fingerprint` là lớp bắt buộc (NOT NULL).

## 5. Index

| Index | Truy vấn phục vụ |
|---|---|
| `ix_shipments_order_id` | tra vận đơn theo đơn hàng (một đơn có thể nhiều vận đơn: giao lại, tách kiện) |
| `ix_shipments_status` | lọc vận đơn theo trạng thái |
| `ix_shipment_events_shipment_id_occurred_at` | lịch sử một vận đơn theo thời gian |
| `ix_shipment_fees_shipment_id` | dòng phí của vận đơn |
| `ix_shipment_reconciliation_shipment_id` | đối soát của vận đơn |
| `ix_shipment_reconciliation_provider_id_statement_reference` | mọi dòng thuộc một bảng kê của hãng |
| `ix_shipping_webhook_events_tracking_number` | tra webhook theo mã vận đơn khi gỡ lỗi |
| `ix_shipping_webhook_events_processing_status_received_at` | hàng đợi phát lại (lấy FAILED/RECEIVED cũ nhất) |
| `ix_shipping_audit_logs_entity_type_entity_id_created_at` | nhật ký của một thực thể |

**Cố ý không tạo** (index do UNIQUE đã phủ, hoặc chưa có truy vấn):

- `shipments.provider_id`, `shipments.tracking_number`: UNIQUE `(provider_id, tracking_number)` đã phủ, vì tra mã vận đơn luôn biết hãng. Nếu sau này cần tìm mã vận đơn mà không biết hãng thì thêm index riêng bằng migration mới.
- `shipment_events.provider_event_id`, `shipping_webhook_events.fingerprint` / `event_id`: UNIQUE kèm `provider_id` đã phủ.
- `shipment_reconciliation.status`: số giá trị ít, chưa có truy vấn. Thêm khi có màn hình đối soát.

Tổng cộng 9 index thường + 10 UNIQUE + 10 PK = 29, cộng PK của `alembic_version` = **30**, khớp số `pg_indexes` đếm được trên PostgreSQL 16 (xem mục 9).

## 6. Tiền: không bao giờ dùng float

- **PostgreSQL: `NUMERIC(18,2)`** cho mọi cột tiền (11 cột: `shipments.cod_amount/estimated_fee/actual_fee`, `shipment_fees.amount`, `shipment_cod.*_amount`, `shipment_reconciliation.*_amount`, `shipment_packages.declared_value`).
  - 18 chữ số, 2 số lẻ: trần 9 999 999 999 999 999,99, dư xa cho VND. Hai số lẻ để dùng được cho tiền tệ có xu sau này. VND hiện không có số lẻ nên luôn `.00`.
- **SQLite: `BIGINT` đơn vị nhỏ nhất (×100)**. SQLite không có kiểu thập phân chính xác: `NUMERIC` rơi về REAL (dấu phẩy động) và mất chữ số. Kiểu `app.db.types.MoneyType` đọc/ghi cả hai dạng, nên code ứng dụng luôn thấy `Decimal`.
- **Tầng ORM chặn**: `float`/`bool` → `TypeError`; quá 2 số lẻ → `ValueError` (không tự làm tròn); vượt trần NUMERIC → `ValueError`.
- **Lưu ý khi ghi SQL tay trên PostgreSQL**: `NUMERIC(18,2)` tự **làm tròn** `1.005 → 1.01` (đo trên PG16). Chỉ ORM mới từ chối. Không ghi tiền bằng SQL tay.
- **Một `currency` cho mỗi dòng** (mặc định `VND`, CHECK độ dài 3). Các cột tiền trên cùng một dòng dùng chung đơn vị tiền tệ đó.
- Kiểm: `test_money_round_trips_exactly_at_max_precision` (giá trị 18 chữ số mà float không giữ nổi). Đã thử cố ý đổi sang float: test hỏng (`9999999999999999.99` → `10000000000000000.00`), rồi khôi phục.

## 7. JSON

- `JSONB` trên PostgreSQL, `JSON` (TEXT) trên SQLite, qua `JSON().with_variant(JSONB(), "postgresql")`.
- Cột JSON: `shipping_accounts.metadata_json`, `shipment_events.metadata_json`, `shipping_webhook_events.payload_json/headers_json`, `shipping_audit_logs.before_json/after_json`.
- **Không cột nghiệp vụ nào đọc vào cấu trúc riêng của một hãng.** Trạng thái, mã vận đơn, tiền đều ở cột riêng; JSON chỉ để tra cứu, gỡ lỗi và phát lại.

## 8. Chính sách bí mật

- **Không có cột nào chứa mật khẩu, token hay khoá riêng.** `shipping_accounts.secret_reference` chỉ giữ **con trỏ** tới nơi cất bí mật: `env://VTP_TOKEN`, `vault://shipping/vtp/main`… DB CHECK chuỗi phải có dạng `scheme://`, nên một chuỗi token trần không lọt vào được. Khi repo chính có secret manager (trình quản lý bí mật) thì chỉ cần thêm scheme mới, không đổi schema.
- **Header webhook dùng danh sách TRẮNG**: chỉ giữ `content-type`, `content-length`, `user-agent`, `x-request-id`, `x-correlation-id`, `x-forwarded-for`, `x-real-ip`. Quên một header ở danh sách trắng chỉ mất một gợi ý gỡ lỗi; quên một header ở danh sách đen là lộ khoá. Vì vậy `Authorization`, `X-Token`, chữ ký… không bao giờ được lưu.
- **Payload webhook, metadata và audit before/after dùng che theo tên khoá**: JSON tự do nên không lập danh sách trắng được. Khoá nào có dạng bí mật (`password`, `token`, `secret`, `api_key`, `authorization`, `private_key`, `credential`, `cookie`, `signature`, và các từ nguyên `pass`/`pwd`/`otp`/`pin`/`key`/`auth`) bị thay bằng `[REDACTED]`, đệ quy. Ví dụ `TOKEN` trong body webhook Viettel Post bị che.
  - **Giới hạn đã biết**: bí mật nằm trong **giá trị** dưới một khoá vô hại (vd `{"note": "token=abc"}`) thì không bị che. Tầng webhook (W-SHP webhook) phải bỏ các trường như vậy trước khi gọi repository.
- `fingerprint` do bên gọi tính trên request thô. Repository không lưu request thô chưa che.
- Migration và test không có credential thật; test chỉ dùng chuỗi giả kiểu `should-not-persist`, `leak-me`.

## 9. Tương thích SQLite / PostgreSQL

| Kiểm | SQLite | PostgreSQL 16.15 |
|---|---|---|
| upgrade head | PASS (pytest) | PASS: SQL offline `alembic upgrade head --sql` nạp bằng `psql` vào cụm tạm |
| downgrade base | PASS (pytest, rồi upgrade lại) | PASS: còn 0 bảng; upgrade lại được 10 bảng |
| Kiểu tiền | BIGINT ×100 | `numeric(18,2)` ×11 cột, 0 cột float/real/double |
| JSON | JSON/TEXT | `jsonb` |
| UNIQUE, CHECK, FK kép, RESTRICT, NULL trong UNIQUE | 38 test repository | 12 câu cố ý sai bằng `psql`: 11 bị đúng ràng buộc chặn; câu `1.005` bị NUMERIC làm tròn thành `1.01` (mục 6) |

**Phạm vi bản chạy PostgreSQL**: cụm `initdb` tạm trong thư mục scratch, chỉ nghe `127.0.0.1:55439`, đã tắt sau khi đo. Kiểm **DDL và ràng buộc bằng SQL**. **Chưa** chạy repository/ORM trên PostgreSQL, vì `requirements.txt` không có driver (psycopg) và thêm driver nằm ngoài phạm vi W-SHP-04. CI hiện chỉ chạy SQLite; không sửa `.github/` (ngoài phạm vi). Việc tiếp theo: xem mục 12.

Khác biệt đã biết:

- SQLite không lưu múi giờ. `UTCDateTime` bắt buộc datetime có múi giờ khi ghi, lưu UTC trần, đọc ra gắn lại UTC. PostgreSQL dùng `TIMESTAMPTZ`.
- SQLite chỉ tự tăng với `INTEGER PRIMARY KEY`, nên id là `INTEGER` trên SQLite và `BIGINT` (BIGSERIAL) trên PostgreSQL.
- SQLite phải bật `PRAGMA foreign_keys=ON` cho từng kết nối. `app/db/session.py` và `migrations/env.py` đều bật; `test_foreign_keys_enforced_on_sqlite` giữ điều đó.
- Server default được viết trung lập (`sa.func.now()`, `sa.true()`), không phải `CURRENT_TIMESTAMP` hay `1` của riêng SQLite. Bản tự sinh đầu tiên của Alembic từng ra dạng SQLite, đã sửa tay.

## 10. Chính sách migration

- **Không tạo schema lúc chạy.** Không có `create_all`, `CREATE TABLE`, `ALTER TABLE` trong `app/`. `test_application_code_never_creates_schema` quét `app/**/*.py` và hỏng nếu có.
- Cấu hình nằm trọn trong `migrations/` (không có `alembic.ini` ở gốc repo):
  ```bash
  alembic -c migrations/alembic.ini -x db_url=sqlite:///./local.db upgrade head
  alembic -c migrations/alembic.ini heads
  ```
  Không có URL mặc định: phải truyền `-x db_url=…` hoặc đặt `DATABASE_URL`, nếu không thì báo lỗi. Migration không bao giờ chạm một DB mà không ai gọi tên.
- Revision là file tự đứng: **không import code ứng dụng**, kiểu dữ liệu đóng băng ngay trong file. Sửa model về sau không viết lại lịch sử.
- `test_migration_matches_orm_metadata`: không có chênh lệch giữa migration và model theo `alembic compare_metadata`. **Phạm vi**: công cụ này so bảng, cột, kiểu, nullable, index, UNIQUE, FK; **không so CHECK**. CHECK được so riêng bằng `test_check_constraints_match_orm` (so tập tên CHECK giữa DB và model). Cả hai chỉ chạy trên SQLite.
- Thêm một `ShipmentStatus` mới **bắt buộc** có migration sửa CHECK. `test_status_check_lists_every_domain_status` hỏng nếu quên.
- Tên ràng buộc ≤ 63 ký tự (giới hạn PostgreSQL), có test.

## 11. Rollback / downgrade

- `downgrade()` xoá cả 10 bảng theo thứ tự ngược FK. **Mất dữ liệu.** Chỉ dùng cho dev/test, hoặc lần triển khai đầu vừa hỏng mà chưa có dữ liệu thật.
- Khi đã có dữ liệu thật: rollback bằng **migration tiến** (thêm revision mới), không downgrade.
- Đã chạy downgrade trên SQLite (pytest và CLI) và trên PostgreSQL 16 (SQL offline).

## 12. Ghi chú tích hợp (Integration notes)

### DOMAIN/DB MAPPING DRIFT WITH W-SHP-01: **YES** — đã hoà giải ở G05

> G05 (`integration/cr-shp-001`): các điểm dưới đây được xử lý trong `app/repositories/mappers.py` và migration `shp_0002_webhook_processing` (sự kiện không canonical, giờ không múi giờ, cột xử lý webhook, gieo `VIETTEL_POST`). Xem `docs/INTEGRATION_NOTES.md` và `docs/DECISIONS.md` D-005…D-015.

So với `feature/shp-core-domain` @ `8515be2e8a351cec548d530173503e8ee21e7a34` (không merge, không cherry-pick, chỉ đọc bằng `git show`). Nhánh này dựng trên baseline `3b89b36`, nên repository trả **bản ghi ORM**, không trả DTO domain. Integration Worker cần khớp:

1. **Hãng**: domain dùng `provider: ShippingProviderCode` (enum); DB dùng `provider_id` → `shipping_providers.code`. Cần seed (gieo sẵn) các dòng `shipping_providers` (migration này **không** seed) và ánh xạ code ↔ id ở service.
2. **Phí**: domain có một `fee: Money`; DB có `estimated_fee`, `actual_fee` và bảng dòng phí `shipment_fees`. Cần chốt `fee` của domain ứng với cột nào.
3. **Tiền tệ**: domain gắn currency vào **từng** `Money` (COD, phí, giá trị khai báo có thể khác đơn vị); DB có **một** `currency` mỗi dòng. Service phải từ chối vận đơn có nhiều đơn vị tiền tệ, hoặc cần migration thêm cột currency riêng.
4. **Độ chính xác**: domain `Money` chỉ `ge=0`, không giới hạn số lẻ; DB/ORM từ chối quá 2 số lẻ và ≥ 10^16. Nên thêm giới hạn này vào domain để lỗi hiện sớm.
5. **COD**: domain `cod_amount: Money | None`; DB `NOT NULL DEFAULT 0`. Ánh xạ `None ↔ 0`.
6. **Sự kiện**: domain `ShipmentEvent` mang `provider` + `tracking_number`; DB mang `shipment_id` + `provider_id` (mã vận đơn lấy qua vận đơn). Field `status` của domain ↔ cột `canonical_status`.
7. **Cập nhật trạng thái**: `Shipment.apply_event` của domain đổi trạng thái vô điều kiện. `append_shipment_event` **không** đổi `shipments.status`; service quyết định (thứ tự sự kiện, luật chuyển trạng thái) và ghi `MANUAL_STATUS_OVERRIDE` khi đổi tay.
8. **Trường chỉ DB có**: `id`, `shipping_account_id`, `created_by`, `created_at`, bảng COD, đối soát, webhook, audit.
9. **Không lệch**: 12 giá trị `ShipmentStatus` giống hệt nhau ở baseline và ở `8515be2`; ràng buộc kiện hàng (khối lượng > 0, kích thước > 0 nếu có) khớp `ShipmentPackage` của domain.

### Việc tiếp theo (follow-up)

- Thêm service PostgreSQL vào CI và chạy chính bộ test repository trên PostgreSQL (cần sửa `.github/workflows/ci.yml` và thêm driver: ngoài phạm vi W-SHP-04).
- Seed `shipping_providers` bằng một migration dữ liệu riêng khi chốt danh sách hãng.
- Nối `app/db/session.py` vào `app/core/container.py` (ngoài phạm vi).
