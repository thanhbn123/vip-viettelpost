# STAGING — chuẩn bị triển khai (G14)

**Trạng thái:** tài liệu và công cụ sẵn sàng; **chưa có môi trường staging được cấp phép** (đo 2026-09-29: repo không có GitHub Environment, không có secret) → G15 = `STAGING ENVIRONMENT REQUIRED`. Không deploy production.

## 1. Thành phần

| Thành phần | Yêu cầu |
|---|---|
| Ứng dụng | Ảnh Docker từ `Dockerfile` (Python 3.11, user uid 10001, cổng 8000). Chạy **sau** reverse proxy HTTPS; không mở cổng 8000 ra Internet |
| CSDL | PostgreSQL **16**, một database riêng cho staging, user riêng chỉ có quyền trên database đó. Không dùng chung với production |
| Job định kỳ | `python -m app.jobs.replay_webhooks` mỗi 5 phút (idempotent), cùng ảnh, cùng biến môi trường |
| Mạng ra | Chỉ tới `https://partnerdev.viettelpost.vn` (môi trường development của VTP) |

## 2. Biến môi trường và bí mật

Bí mật lấy từ kho bí mật của nền tảng (GitHub Environment `staging`, Vault, v.v.) — **không** file `.env` trong ảnh, **không** commit.

| Biến | Bí mật? | Giá trị staging |
|---|---|---|
| `APP_ENV` | không | `staging` (chỉ để nhận diện; mã hiện **không** đọc biến này — không có chốt chặn nào dựa vào nó) |
| `DATABASE_URL` | **có** | `postgresql+psycopg://<user>:<pass>@<host>:5432/<db_staging>` |
| `VTP_BASE_URL` | không | `https://partnerdev.viettelpost.vn` (**không** dùng production) |
| `VTP_USERNAME` / `VTP_PASSWORD` **hoặc** `VTP_TOKEN` | **có** | Tài khoản **development** do VTP cấp (R-001: chưa có) |
| `VTP_TIMEOUT_SECONDS` | không | `20` |
| `VTP_WEBHOOK_TIMEZONE` | không | **để trống** tới khi VTP xác nhận múi giờ (D-006, R-002) |
| `WEBHOOK_SHARED_SECRET` | **có** | Chuỗi ngẫu nhiên ≥ 32 ký tự; đăng ký cùng giá trị với VTP làm `TOKEN` |
| `API_KEYS` | **có** (dạng băm) | `<id>:<sha256>` sinh bằng `python -m app.tools.api_key <id>` — lệnh **in key thô ra màn hình**: chỉ chạy trên terminal tin cậy, không chạy trong CI hay nơi log bị thu; key thô giao qua kênh bí mật |
| `DB_CONNECT_TIMEOUT_SECONDS` | không | `5` |
| `LOG_FORMAT` / `LOG_LEVEL` | không | `json` / `INFO` |
| `PROVIDER_RETRY_*`, `API_MAX_BODY_BYTES`, `WEBHOOK_MAX_BODY_BYTES` | không | mặc định |

## 3. Yêu cầu URL webhook

- `https://<staging-host>/api/v1/shipping/webhooks/viettel-post`, HTTPS với chứng chỉ hợp lệ, POST JSON.
- Đăng ký với Viettel Post (môi trường dev) kèm `TOKEN` = `WEBHOOK_SHARED_SECRET`.
- Route này **không** dùng API key (xác thực bằng `TOKEN` trong thân); các route `/api/v1/shipping/*` còn lại bắt buộc `X-API-Key`.
- Tài liệu VTP không công bố dải IP gọi đến → chưa thể lọc IP; nếu VTP cung cấp thì thêm ở proxy.
- VTP thử lại tối đa 5 lần tới khi nhận 200: ứng dụng trả 5xx khi lỗi lưu trữ để được gửi lại.

## 4. Quy trình migration (trước khi bật ứng dụng)

Chạy từ bản checkout đúng commit sẽ triển khai (hoặc trong ảnh đó), với `DATABASE_URL` đã nạp từ kho bí mật vào **biến môi trường** (không truyền qua `-x db_url=…`: tham số dòng lệnh hiện trong `ps`). `migrations/env.py` tự đọc `DATABASE_URL`.

```bash
set -euo pipefail
# 0. Chuỗi kết nối cho công cụ libpq (pg_dump KHÔNG hiểu dạng "postgresql+psycopg://").
#    Đặt từ kho bí mật, dạng postgresql://<user>:<pass>@<host>:5432/<db>, hoặc dùng PG* + ~/.pgpass.
: "${DATABASE_URL_PSQL:?chua dat DATABASE_URL_PSQL}"
: "${DATABASE_URL:?chua dat DATABASE_URL}"
# 1. Sao lưu và KIỂM bản sao lưu (staging mới, CSDL rỗng thì vẫn chạy để có mốc)
f="before-$(date +%Y%m%d%H%M).dump"
pg_dump --format=custom --file="$f" --dbname="$DATABASE_URL_PSQL"
pg_restore --list "$f" > /dev/null
# 2. Xem trước
alembic -c migrations/alembic.ini current
alembic -c migrations/alembic.ini history
# 3. Nâng
alembic -c migrations/alembic.ini upgrade head
# 4. Kiểm: phải in "shp_0004_shipments_created_index (head)"
alembic -c migrations/alembic.ini current
```

Ứng dụng **không bao giờ** tự tạo/sửa schema. `/health/ready` trả 503 nếu revision CSDL ≠ head của mã đang chạy.

## 5. Rollback

**Mã và schema gắn với nhau:** readiness đòi revision CSDL **bằng đúng** head của mã. Lùi một phía mà không lùi phía kia → dịch vụ 503 (không nhận tải) cho tới khi hai bên khớp. Vì vậy:

| Mức | Thứ tự |
|---|---|
| Chỉ lùi mã, schema giữ nguyên | Chỉ làm khi bản mã cũ có **cùng** head migration; nếu không, làm theo dòng dưới |
| Lùi mã **và** schema | 1) Ngưng nhận tải (tắt route ở proxy / scale 0) và tạm dừng job replay. 2) Sao lưu + kiểm (§4 bước 1). 3) Lùi schema **từng revision** tới head của bản mã cũ. 4) Triển khai ảnh cũ. 5) `/health/ready` = 200 + smoke test. 6) Mở lại tải. Webhook VTP bị từ chối trong lúc ngưng sẽ được VTP gửi lại (tối đa 5 lần) — giữ cửa sổ ngắn |
| Các bước lùi schema | `alembic … downgrade shp_0003_active_order_guard` (bỏ index danh sách) → `… downgrade shp_0002_webhook_processing` (bỏ khoá thao tác + index một phần) → `… downgrade shp_0001_shipping_gateway` **bị từ chối** khi còn sự kiện không có canonical **hoặc không có `occurred_at`** (D-015). Khi `VTP_WEBHOOK_TIMEZONE` để trống thì mọi sự kiện VTP đều không có `occurred_at` → trên thực tế **không lùi được qua shp_0002** khi đã có dữ liệu; phải khôi phục từ bản sao lưu. Không bao giờ downgrade về `base` khi có dữ liệu |
| Dữ liệu | `pg_restore` từ bản đã kiểm ở §4 bước 1 |

## 6. Kiểm tra sức khoẻ

- Liveness: `GET /health` → 200.
- Readiness: `GET /health/ready` → 200 khi CSDL kết nối được, migration đúng head, có `WEBHOOK_SHARED_SECRET`, có `API_KEYS` hợp lệ, có credential VTP. Trả 503 kèm tên kiểm tra hỏng (không lộ giá trị).
- Số đo: `GET /metrics` (cần `X-API-Key`).
- Giám sát: mỗi lần chạy `python -m app.jobs.replay_webhooks` ghi `unmatched_with_shipment=<n>` và **thoát mã 3** khi n > 0 — bộ lập lịch cảnh báo khi mã ≠ 0 lặp lại nhiều lần liền (một lần lẻ có thể là hãng còn đang thử lại).

## 7. Checklist triển khai

- [ ] Có môi trường staging được cấp phép, tách khỏi production (R-008)
- [ ] PostgreSQL 16 staging + user riêng; `DATABASE_URL` trong kho bí mật
- [ ] Credential VTP **development** (R-001) trong kho bí mật; `VTP_BASE_URL` = partnerdev
- [ ] `WEBHOOK_SHARED_SECRET` sinh mới, đăng ký với VTP; URL webhook HTTPS
- [ ] `API_KEYS` sinh bằng `app.tools.api_key`; key thô giao qua kênh bí mật
- [ ] Ảnh dựng từ commit `develop` đã có CI xanh (4 job: lint, test, postgres, image)
- [ ] Migration `upgrade head` chạy riêng, `current` = `shp_0004_shipments_created_index`
- [ ] Ứng dụng khởi động; `/health/ready` = 200
- [ ] `python scripts/smoke_test.py` = 9/9 PASS
- [ ] Job `replay_webhooks` được lên lịch 5 phút
- [ ] Log ứng dụng JSON không có bí mật (lọc che bật sẵn); kiểm vài dòng thật. Access log của uvicorn vẫn là chữ thường (không qua lớp che, chỉ có đường dẫn) — tắt bằng `--no-access-log` nếu proxy đã ghi access log
- [ ] Ghi SHA đã triển khai + kết quả smoke vào `docs/MASTER_STATUS.md` (G15)

## 8. Smoke test

Chạy từ bản checkout repo (ảnh Docker không chứa `scripts/`) sau `pip install -r requirements-dev.txt`. Nhập key không để lại lịch sử shell:

```bash
export SMOKE_BASE_URL=https://<staging-host>
stty -echo; printf "API key: "; read SMOKE_API_KEY; stty echo; echo
export SMOKE_API_KEY
python scripts/smoke_test.py
unset SMOKE_API_KEY
```

Chỉ đọc (verifier PR #22 đo: số dòng 11 bảng không đổi trước/sau): không tạo/huỷ vận đơn, không gọi Viettel Post. 9 kiểm tra: liveness, readiness, header bảo mật, API từ chối khi thiếu key, API nhận key và `VIETTEL_POST` bật, danh sách vận đơn, `/metrics` sau key, webhook từ chối `TOKEN` sai (không ghi gì), lỗi không lộ nội bộ (chỉ kiểm được đường 404; lỗi 5xx được phủ bằng test tự động, không bằng smoke). Bản thân script có test chạy trên ứng dụng thật trong tiến trình (`tests/integration/test_smoke_script.py`).

## 9. Kiểm tra chấp nhận staging (G15) — khi có môi trường

Ngoài smoke test: tạo vận đơn thử trên VTP dev (nếu được phép) → huỷ; gửi webhook thử (hoặc chờ VTP dev gọi) → kiểm idempotency (gửi lại cùng payload), lưu bền, cập nhật trạng thái, audit; tắt CSDL ngắn → webhook trả 5xx rồi phục hồi qua lần gửi lại / job; kiểm log không lộ bí mật; diễn tập rollback một revision migration.
