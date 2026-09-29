# STAGING REQUIREMENTS — những gì cần có để chạy G08 và G15

**Đo 2026-09-29** (`develop` `d580cc353605e4705995c25308e0bbf84df54daa`): trước khi làm repo có 0 GitHub Environment, 0 secret, 0 variable (sau đó Environment `staging` được tạo **rỗng**, vẫn 0 secret/variable); không tài liệu/issue nào chỉ định máy staging → **`STAGING_TARGET_MISSING`**, **`BLOCKED_EXTERNAL_CREDENTIAL`**. Mọi thứ phía mã đã sẵn: ảnh Docker, migration, runbook (`STAGING.md`), smoke test, workflow `staging.yml`, script `vtp_dev_e2e.py`.

## 1. Compute / runtime
- Máy/nền tảng chạy **container Linux x86_64 hoặc arm64**, Docker (hoặc tương đương) chạy được ảnh từ `Dockerfile` (Python 3.11-slim, uid 10001, cổng 8000).
- Tối thiểu khuyến nghị cho staging: 1 vCPU, 512 MB RAM cho ứng dụng (chưa đo tải — ước lượng, xem `POSTGRES_VERIFICATION.md` "ngoài phạm vi").
- Có lịch chạy định kỳ (cron/systemd timer/scheduler) cho `python -m app.jobs.replay_webhooks` mỗi 5 phút, cùng ảnh và biến môi trường.
- Ra Internet tới `https://partnerdev.viettelpost.vn` (443). **Tách biệt** mọi tài nguyên production.

## 2. PostgreSQL
- **PostgreSQL 16**, database riêng cho staging, user riêng chỉ có quyền trên database đó (CREATE trong schema `public` để chạy migration).
- Mã hoá kết nối nếu DB không cùng máy (thêm `?sslmode=require` vào `DATABASE_URL`).
- Không dùng chung server/credential với production.
- Có cách sao lưu (`pg_dump`) và khôi phục trước mỗi migration (`STAGING.md` §4).

## 3. HTTPS / domain
- Một hostname riêng cho staging (vd. `shipping-staging.<domain>` — chủ dự án chọn), chứng chỉ TLS hợp lệ, reverse proxy HTTPS → container cổng 8000.
- Cổng 8000 **không** mở ra Internet; chỉ proxy tới được.
- Proxy chuyển `X-Forwarded-*`; ảnh chạy `--proxy-headers` (tin 127.0.0.1 mặc định của uvicorn — nếu proxy ở máy khác, cần cấu hình `--forwarded-allow-ips`, ghi vào `STAGING_DEPLOYMENT.md` khi chọn target).

## 4. Webhook URL
- `https://<staging-host>/api/v1/shipping/webhooks/viettel-post`, POST JSON, không cần API key (xác thực bằng `TOKEN` trong thân).
- Đăng ký với Viettel Post (môi trường **dev**) kèm `TOKEN` = `WEBHOOK_SHARED_SECRET`.
- VTP không công bố dải IP gọi đến → chưa lọc được IP.

## 5. GitHub Environment
- Tên: **`staging`**; deployment branches: `develop` và `deploy/staging`; required reviewer: chủ dự án (`GITHUB_ENVIRONMENT_STAGING.md` §C).

## 6. GitHub Secrets (Environment `staging`)
REQUIRED SECRET: `DATABASE_URL`, `WEBHOOK_SHARED_SECRET`, `API_KEYS`, `SMOKE_API_KEY`, và **một trong hai**: `VTP_TOKEN` **hoặc** (`VTP_USERNAME` + `VTP_PASSWORD`).
OPTIONAL SECRET: `DATABASE_URL_PSQL` (chỉ nếu sao lưu chạy từ Actions); credential của cơ chế deploy (tên đặt khi chọn target).
Chi tiết từng biến: `GITHUB_ENVIRONMENT_STAGING.md`.

## 7. Non-secret variables
REQUIRED: `STAGING_BASE_URL`, `STAGING_DEPLOY_METHOD`; cho G08: `VTP_E2E_SCENARIO_JSON`.
OPTIONAL: `VTP_BASE_URL` (nếu đặt phải là URL dev), `VTP_TIMEOUT_SECONDS`, `VTP_WEBHOOK_TIMEZONE` (để trống), `WEBHOOK_MAX_BODY_BYTES`, `API_MAX_BODY_BYTES`, `DB_CONNECT_TIMEOUT_SECONDS`, `LOG_LEVEL`, `LOG_FORMAT` (`json`), `PROVIDER_RETRY_*`, `APP_ENV`, `RUN_VTP_DEV_E2E`, `VTP_E2E_ALLOW_CREATE`, `VTP_E2E_CREATE_TEST_ORDER`.

## 8. Migration
`STAGING.md` §4 (chạy dạng file; sao lưu + `pg_restore --list`; `alembic upgrade head`; kỳ vọng `shp_0004_shipments_created_index (head)`). Workflow `staging.yml` kiểm trước: đúng một head.

## 9. Rollback
`STAGING.md` §5: mã và schema gắn nhau (readiness đòi đúng head); lùi schema từng revision; không lùi qua `shp_0002` khi đã có sự kiện không `occurred_at` → khôi phục từ bản sao lưu. Ảnh được gắn tag theo SHA (`staging-<sha>`) để quay lại SHA trước.

## 10. Health / smoke
`/health` (liveness), `/health/ready` (CSDL, migration head, webhook secret, API keys, credential VTP — chỉ có/không), `/metrics` (cần key); `scripts/smoke_test.py` 9 kiểm tra chỉ đọc (`STAGING.md` §8).

## 11. Credential Viettel Post DEVELOPMENT
- Tài khoản Partner trên **partnerdev.viettelpost.vn** (không phải production): `VTP_USERNAME` + `VTP_PASSWORD`, **hoặc** token dài hạn `VTP_TOKEN`.
- Danh sách ID tỉnh/xã (và huyện nếu có) của 2 địa chỉ **thử** để điền `VTP_E2E_SCENARIO_JSON` (R-006: app chưa tra tên → ID).
- Xác nhận VTP cho phép tạo đơn thử trên dev và cách huỷ; quyết định `order_payment` (D-BIZ-001) trước khi tạo đơn.
- Chi tiết: `VTP_DEV_E2E.md`.

## 12. Owner actions
1. Environment `staging` **đã được tạo rỗng** (0 secret; chỉ `develop` và `deploy/staging`; anh là người duyệt bắt buộc) — và **tự thêm secret trực tiếp trong GitHub** — không gửi qua chat.
2. Chỉ định staging target: hostname/IP hoặc nền tảng; cơ chế deploy (SSH/…); có được cho GitHub Actions deploy không; domain/subdomain; đã có reverse proxy HTTPS chưa.
3. Cấp PostgreSQL 16 staging (host, port, db, user) → đặt `DATABASE_URL`.
4. Cấp credential VTP **development** → `VTP_TOKEN` hoặc `VTP_USERNAME`/`VTP_PASSWORD`; gửi địa chỉ thử + ID địa danh → `VTP_E2E_SCENARIO_JSON`.
5. Đăng ký URL webhook staging với VTP dev + `WEBHOOK_SHARED_SECRET`.
6. Quyết định mở (không chặn staging, chặn production): `DECISIONS.md` mục "Quyết định còn mở"; riêng D-BIZ-001 (`order_payment`) cần có trước bước tạo đơn thử của G08.
7. Khuyến nghị: ruleset cho `develop` và `deploy/staging` (chỉ chủ dự án được cập nhật, không force push) — hiện repo PUBLIC và không có bảo vệ nhánh nào.
