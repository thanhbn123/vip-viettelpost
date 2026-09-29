# STAGING DEPLOYMENT — cách ứng dụng chạy ở staging

Trạng thái target: **`STAGING_TARGET_MISSING`** (2026-09-29). Workflow `.github/workflows/staging.yml` đã có nhưng bước deploy **dừng có chủ đích** tới khi chủ dự án chọn target; không có bước nào chạm production.

| # | Mục | Quy định |
|---|---|---|
| 0 | Kích hoạt | (a) Đẩy nhánh `deploy/staging` trỏ tới một commit **đã có** trên `develop` **và có chứa `staging.yml`** (tức là từ commit merge PR #25 trở đi; commit cũ hơn không kích hoạt được) — `git push origin <sha>:refs/heads/deploy/staging`; (b) *Actions → Staging → Run workflow* với input `sha` — GitHub chỉ hiện nút này khi file workflow có trên nhánh mặc định `main` (sau main review); khi chạy phải chọn *Use workflow from: `develop`* vì Environment chỉ cho `develop` và `deploy/staging`. Mọi job dùng Environment `staging` chờ chủ dự án duyệt |
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
| 13 | Rollback ảnh/SHA | Triển khai lại `staging-<sha trước>` (qua workflow chỉ được với SHA có chứa `staging.yml`; SHA cũ hơn: dựng ảnh bằng tay cùng lệnh ở mục 1); nếu khác migration head thì theo thứ tự ở `STAGING.md` §5 |
| 14 | Smoke test | `scripts/smoke_test.py` với `SMOKE_BASE_URL` = `STAGING_BASE_URL`, `SMOKE_API_KEY` (secret); 9/9 mới coi là triển khai xong |
| 15 | Phục hồi lỗi | Readiness 503 → xem trường `checks` (tên kiểm hỏng); CSDL mất → webhook trả 5xx và VTP gửi lại (≤ 5 lần), job replay áp các dòng `FAILED`/`IGNORED` sau đó; migration lỗi → khôi phục bản sao lưu vừa kiểm, triển khai lại SHA trước |

## Target (chủ dự án cung cấp)

- Hostname/IP **hoặc** nền tảng triển khai.
- Cơ chế deploy (SSH + Docker, nền tảng PaaS, …) và việc GitHub Actions có được phép deploy không.
- Domain/subdomain staging; đã có reverse proxy HTTPS chưa.
- PostgreSQL 16: host, port, database, user (mật khẩu đưa thẳng vào secret `DATABASE_URL`).

Khi có target: em cài cơ chế deploy tương ứng vào bước "Deploy" của `staging.yml`, đặt tên secret của cơ chế đó vào `GITHUB_ENVIRONMENT_STAGING.md` §B, rồi chạy G15 theo `STAGING.md` §9.

## Deploy contract (CR-STG-001)

`STAGING_DEPLOY_METHOD` là **allowlist**: một method chỉ tồn tại khi file hook `scripts/staging/methods/<method>.sh` được commit (tên khớp `^[a-z0-9][a-z0-9-]{1,40}$`). **Hiện chưa có hook nào** — chủ dự án chưa chọn target, nên em không tự chọn VPS/nền tảng nào.

Workflow gọi `scripts/staging/deploy.sh <phase>`; dispatcher kiểm tên method, hook tồn tại, `STAGING_SHA` 40-hex, rồi chạy `bash <hook> <phase>`. Hook nhận:

| Biến | Ý nghĩa |
|---|---|
| `STAGING_SHA` | commit đang triển khai |
| `STAGING_IMAGE_ARCHIVE` | ảnh `docker save \| gzip` của đúng SHA (tag `vip-shipping-gateway:staging-<sha>`, có `APP_GIT_SHA`) — cho `migrate`, `start` |
| `STAGING_ENV_FILE` | file quyền 600 chứa biến runtime (tạo từ secret, không in) — cho `migrate`, `start` |

| Phase | Hook phải làm | Thất bại |
|---|---|---|
| `migrate` | Sao lưu + `alembic -c migrations/alembic.ini upgrade head` bằng **ảnh mới** với `STAGING_ENV_FILE`, rồi kiểm `current` = head | exit ≠ 0 → workflow dừng, ảnh cũ vẫn chạy |
| `start` | Chạy ảnh mới (giữ ảnh/SHA trước để rollback), cổng 8000 sau proxy HTTPS, restart policy | exit ≠ 0 |
| `rollback` | Quay về release trước (ảnh + nếu cần schema theo `STAGING.md` §5) | exit ≠ 0 → cần người xử |
| `logs` | In log ứng dụng gần nhất ra stdout (để acceptance quét) | exit ≠ 0 → `log_redaction` = NOT_RUN → không đạt |

Cắm một target = thêm **một** file hook + đặt `STAGING_DEPLOY_METHOD`; **không** sửa mã nghiệp vụ. Tiêu chí nhận hook: có test/bằng chứng chạy được với target thật, qua PR + verifier.
