# STAGING DEPLOYMENT — cách ứng dụng chạy ở staging

Trạng thái target: **`STAGING_TARGET_MISSING`** (2026-09-29). Workflow `.github/workflows/staging.yml` đã có nhưng bước deploy **dừng có chủ đích** tới khi chủ dự án chọn target; không có bước nào chạm production.

| # | Mục | Quy định |
|---|---|---|
| 0 | Kích hoạt | (a) Đẩy nhánh `deploy/staging` trỏ tới một commit **đã có** trên `develop` (`git push origin <sha>:refs/heads/deploy/staging`) — dùng được ngay; (b) *Actions → Staging → Run workflow* với input `sha` — GitHub chỉ hiện nút này khi file workflow có trên nhánh mặc định `main` (sau main review). Mọi job dùng Environment `staging` chờ chủ dự án duyệt |
| 1 | Image/build | `docker build -t vip-shipping-gateway:staging-<sha> .` từ **đúng** commit trên `develop` (workflow kiểm SHA 40 ký tự và `merge-base --is-ancestor`), sau khi ruff + pytest + kiểm một migration head đạt |
| 2 | Runtime | Python 3.11 (ảnh `python:3.11-slim`), phụ thuộc runtime `requirements.txt` (FastAPI 0.141.1, Starlette 1.7.0, SQLAlchemy 2.0.36, Alembic 1.14.0, psycopg 3.2.3, tzdata) |
| 3 | Lệnh container | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers` (CMD của ảnh). Job định kỳ: `python -m app.jobs.replay_webhooks` (thoát 0 = sạch, 3 = còn sự kiện chưa gắn được) |
| 4 | Cổng | Container 8000 → chỉ reverse proxy truy cập; Internet chỉ thấy 443 của proxy |
| 5 | Health | Liveness `GET /health`; readiness `GET /health/ready` (200/503) — dùng cho orchestrator/LB |
| 6 | Kết nối CSDL | `DATABASE_URL` (PostgreSQL 16), `connect_timeout` = `DB_CONNECT_TIMEOUT_SECONDS` (5 s), `pool_pre_ping` |
| 7 | Migration | Bước **riêng, trước** khi bật ảnh mới: `STAGING.md` §4 (`alembic -c migrations/alembic.ini upgrade head`, đọc `DATABASE_URL` từ môi trường). Ứng dụng không tự tạo schema |
| 8 | Webhook URL | `https://<staging-host>/api/v1/shipping/webhooks/viettel-post` |
| 9 | HTTPS | Bắt buộc (workflow từ chối `STAGING_BASE_URL` không phải `https://`) |
| 10 | Nạp biến | Từ Environment `staging` (secret + variable, `GITHUB_ENVIRONMENT_STAGING.md`) vào container qua cơ chế của target (vd. file env quyền 600 do deploy tạo, hoặc secret store của nền tảng). Không có `.env` trong ảnh (`.dockerignore`) |
| 11 | Log | stdout/stderr của container; `LOG_FORMAT=json`; nơi thu log do target quyết định (journald/docker logs/nền tảng). Lớp che bí mật bật sẵn; access log uvicorn là chữ thường |
| 12 | Restart policy | `unless-stopped`/`always` (hoặc tương đương của nền tảng); readiness 503 không được tính là "chết" để khỏi vòng khởi động lại khi đang migration |
| 13 | Rollback ảnh/SHA | Triển khai lại `staging-<sha trước>`; nếu khác migration head thì theo thứ tự ở `STAGING.md` §5 |
| 14 | Smoke test | `scripts/smoke_test.py` với `SMOKE_BASE_URL` = `STAGING_BASE_URL`, `SMOKE_API_KEY` (secret); 9/9 mới coi là triển khai xong |
| 15 | Phục hồi lỗi | Readiness 503 → xem trường `checks` (tên kiểm hỏng); CSDL mất → webhook trả 5xx và VTP gửi lại (≤ 5 lần), job replay áp các dòng `FAILED`/`IGNORED` sau đó; migration lỗi → khôi phục bản sao lưu vừa kiểm, triển khai lại SHA trước |

## Target (chủ dự án cung cấp)

- Hostname/IP **hoặc** nền tảng triển khai.
- Cơ chế deploy (SSH + Docker, nền tảng PaaS, …) và việc GitHub Actions có được phép deploy không.
- Domain/subdomain staging; đã có reverse proxy HTTPS chưa.
- PostgreSQL 16: host, port, database, user (mật khẩu đưa thẳng vào secret `DATABASE_URL`).

Khi có target: em cài cơ chế deploy tương ứng vào bước "Deploy" của `staging.yml`, đặt tên secret của cơ chế đó vào `GITHUB_ENVIRONMENT_STAGING.md` §B, rồi chạy G15 theo `STAGING.md` §9.
