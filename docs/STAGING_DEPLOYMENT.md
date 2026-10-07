# STAGING DEPLOYMENT — cách ứng dụng chạy ở staging

Trạng thái target (2026-09-30): chủ dự án chọn **VPS Linux riêng** → method `vps` đã có trong repo (**DESIGNED/TESTED**, xem mục *Method `vps`*), nhưng Environment `staging` chưa có secret/variable nên workflow vẫn dừng ở preflight với **`STAGING_TARGET_MISSING`**. Chưa có lần deploy thật nào; không có bước nào chạm production.

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

`STAGING_DEPLOY_METHOD` là **allowlist**: một method chỉ tồn tại khi file hook `scripts/staging/methods/<method>.sh` được commit (tên khớp `^[a-z0-9][a-z0-9-]{1,40}$`). **Hiện có đúng một hook: `vps`** (CR-STG-VPS). Input riêng của từng method được preflight kiểm khi method đó được chọn (`METHOD_REQUIREMENTS` trong `scripts/staging/preflight.py`).

Workflow gọi `scripts/staging/deploy.sh <phase>`; dispatcher kiểm tên method, hook tồn tại, `STAGING_SHA` 40-hex, rồi chạy `bash <hook> <phase>`. Hook nhận:

| Biến | Ý nghĩa |
|---|---|
| `STAGING_SHA` | commit đang triển khai |
| `STAGING_IMAGE_ARCHIVE` | ảnh `docker save \| gzip` của đúng SHA (tag `vip-shipping-gateway:staging-<sha>`, có `APP_GIT_SHA`) — cho `migrate`, `start` |
| `STAGING_ENV_FILE` | file quyền 600 chứa biến runtime (tạo từ secret, không in) — cho `migrate`, `start` |

| Phase | Hook phải làm | Thất bại |
|---|---|---|
| `migrate` | Sao lưu + `alembic -c migrations/alembic.ini upgrade head` bằng **ảnh mới** với `STAGING_ENV_FILE`, rồi kiểm `current` = head | exit ≠ 0 → workflow dừng, ảnh cũ vẫn chạy |
| `start` | Chạy ảnh mới (giữ ảnh/SHA trước để rollback), cổng 8000 sau proxy HTTPS, restart policy. **Hoặc** đổi hẳn sang bản mới, **hoặc** để nguyên bản cũ chạy — không được bỏ dở ở trạng thái không có bản nào | exit ≠ 0 → workflow gọi `rollback` |
| `rollback` | Quay về release trước (ảnh + nếu cần schema theo `STAGING.md` §5). Phải **an toàn khi chạy lúc không có gì thay đổi** (được gọi cả sau `start` hỏng giữa chừng, bị huỷ, quá giờ) | exit ≠ 0 → cần người xử |
| `logs` | In log ứng dụng gần nhất của **đúng instance vừa start** ra stdout (JSON, gồm trường `request_id`) — đủ để thấy các request của lần acceptance | exit ≠ 0, rỗng, hoặc không có request id của lần chạy → `log_redaction` = NOT_RUN → không đạt |

Cắm một target = thêm **một** file hook + đặt `STAGING_DEPLOY_METHOD`; **không** sửa mã nghiệp vụ. Tiêu chí nhận hook: có test tự động + PR + verifier; bằng chứng chạy với target thật chỉ có ở lần deploy thật đầu tiên và được ghi riêng (`vps`: chưa có).

## Method `vps` (CR-STG-VPS, issue #35)

**Trạng thái: DESIGNED/TESTED — chưa REAL VPS VERIFIED.** Hook đã có test tự động với transport giả (`tests/unit/test_staging_vps_method.py`: `ssh`/`docker`/`curl` giả, không mạng). Chưa lần nào chạy trên một VPS thật; bằng chứng thật chỉ có sau lần deploy đầu tiên qua workflow.

Chủ dự án chốt 2026-09-30: target staging = **một VPS Linux riêng** (không dùng VPS, CSDL hay credential production).

**Cách chạy:** workflow → `deploy.sh <phase>` → `methods/vps.sh` (trên runner GitHub) → SSH → `scripts/staging/vps/remote.sh` chạy **trên VPS**. Script remote được gửi dạng base64 trong dòng lệnh SSH (không cài gì lên VPS, không `git pull`); stdin chỉ dùng để chuyển file env và ảnh. Bước giải mã chạy dưới login shell của user deploy (thường là `dash`): giải mã hỏng/rỗng → `REMOTE_BOOTSTRAP_FAILED`, exit 97 (không bao giờ thành "xanh mà không làm gì"). Mọi giá trị trên dòng lệnh SSH đã được kiểm định dạng; **secret chỉ đi qua stdin**, không bao giờ nằm trên dòng lệnh hay trong log.

| Phase | Việc (trên VPS, sau bước kiểm staging) | Thất bại |
|---|---|---|
| `migrate` | (1) nhận file env → `$STAGING_APP_DIR/env/<sha>.env` quyền 600, phải có dòng `APP_ENV=staging`; (2) `docker load` ảnh của đúng SHA, kiểm `APP_GIT_SHA` trong ảnh = SHA; (3) kiểm PostgreSQL `server_version_num` bắt đầu bằng `16`; (4) `pg_dump -Fc` → `$STAGING_APP_DIR/backups/<utc>-<sha>.dump`; (5) `alembic upgrade head` bằng **ảnh mới**; (6) `alembic current` phải có `(head)` | `IMAGE_SHA_MISMATCH`, `PG_CHECK_FAILED`, `PG_VERSION_NOT_16`, `BACKUP_FAILED`, `MIGRATION_FAILED`, `MIGRATION_NOT_AT_HEAD` → exit ≠ 0, bản cũ vẫn chạy |
| `start` | Dừng container `vip-staging-app` cũ (giữ lại), chạy `vip-staging-app-next` từ `vip-shipping-gateway:staging-<sha>`, `127.0.0.1:$STAGING_APP_PORT→8000`, `--restart unless-stopped`, nhãn `vip.sha=<sha>`; đợi `GET /health` = 200 rồi `GET /health/ready` = 200 **và** `version` = đúng SHA; đạt thì xoá container cũ, đổi tên, ghi `state/current_sha` và `state/previous_sha` | `HEALTH_FAILED`, `READINESS_FAILED`, `DEPLOYED_SHA_MISMATCH` → xoá bản mới, **bật lại container cũ**, exit ≠ 0 (container cũ chỉ *ready* lại nếu `migrate` vừa rồi không đổi schema — xem *Rollback — giới hạn thật*) |
| `rollback` | Nếu SHA hỏng chưa từng thành `current` → `ROLLBACK_NOOP` (bật lại bản đang có). Nếu đã thành `current` → chạy lại **đúng** `previous_sha` theo cùng quy trình kiểm SHA ở `start` | `ROLLBACK_NO_PREVIOUS_RELEASE` (lần deploy đầu: dừng bản hỏng), `ROLLBACK_FAILED` (bản hỏng được bật lại, job đỏ) → cần người xử |
| `logs` | `docker logs --tail 2000 vip-staging-app` | exit ≠ 0 |

**Chốt chặn staging / chống nhầm production (fail closed):**
1. Trên VPS phải có file `$STAGING_APP_DIR/STAGING_TARGET`, dòng đầu **đúng** `vip-viettelpost staging`. Thiếu hoặc sai → `STAGING_GUARD`, không đổi gì (kiểm ở **mọi** phase, trước mọi thao tác).
2. File env phải có `APP_ENV=staging` (workflow tự ghi; kiểm cả ở runner lẫn VPS).
3. User SSH không được là `root`; trên VPS `id -u` ≠ 0.
4. Tuỳ chọn `STAGING_EXPECTED_HOSTNAME`: `hostname` của VPS phải khớp.
5. Tuỳ chọn `STAGING_HOST_DENYLIST` (danh sách host/IP production, cách nhau bằng dấu phẩy): `STAGING_SSH_HOST` trùng → `PRODUCTION_GUARD`, dừng **trước khi** kết nối.
6. `STAGING_APP_DIR` phải là đường dẫn tuyệt đối ≥ 2 cấp, không `.`/`..`. Script không bao giờ `rm -rf` thư mục; chỉ xoá container của chính nó và file tạm.

**SSH:** khoá riêng chỉ từ secret, ghi vào thư mục `mktemp` quyền 600, xoá khi thoát (`trap`); `StrictHostKeyChecking=yes` với `UserKnownHostsFile` lấy từ secret `STAGING_SSH_KNOWN_HOSTS` (không bao giờ `StrictHostKeyChecking=no`); `BatchMode=yes`, `IdentitiesOnly=yes`.

**Ảnh bất biến:** ảnh dựng trong chính lần chạy workflow từ đúng SHA, chuyển bằng `docker save | gzip` → `docker load`, tag `vip-shipping-gateway:staging-<sha>`. Không registry, không tag `latest`. Ảnh công cụ PostgreSQL mặc định `postgres:16` (đổi được bằng `STAGING_PG_TOOLS_IMAGE`, cấm `:latest`, cho phép ghim `@sha256:`).

### Rollback — giới hạn thật

**`APPLICATION_ROLLBACK_ONLY`.** Rollback chỉ đổi **ảnh/container** về SHA trước. **Schema CSDL không bị hạ** (không `alembic downgrade` tự động). Hệ quả:
- **Rollback tự động chỉ thành công khi bản hỏng KHÔNG thêm migration.** `/health/ready` trả 503 mỗi khi `alembic_version` trong CSDL khác head của ảnh đang chạy (`app/api/health.py`), mà rollback đòi readiness 200 + đúng SHA. Nên nếu bản hỏng đã chạy migration (kể cả migration tương thích ngược), bản cũ **không bao giờ** ready lại: rollback báo `ROLLBACK_FAILED` (kèm gợi ý này), bật lại bản hỏng, job đỏ. Cũng vì vậy, khi `start` hỏng sau một `migrate` có đổi schema thì container cũ được bật lại nhưng ở trạng thái *not ready*.
- Khi đó phải xử theo `STAGING.md` §5 (downgrade có kiểm soát hoặc khôi phục từ `backups/<utc>-<sha>.dump`), **do người làm**, không tự động; rồi mới rollback/triển khai lại.
- Triển khai lại một SHA cũ **qua workflow** sẽ dừng ở `migrate` nếu CSDL đã ở revision mới hơn mà ảnh cũ không biết (`alembic` báo lỗi) — đúng kiểu fail closed. Muốn quay về bản cũ thì dùng phase `rollback`.
- Rollback chỉ lùi **một** bước (`previous_sha` bị xoá sau khi dùng) để không nhảy qua lại. Không có biến chọn SHA rollback tuỳ ý: quay về SHA khác thì triển khai SHA đó qua workflow.
- Mỗi phase (trừ `logs`) giữ khoá `$STAGING_APP_DIR/state/lock` (thư mục + PID): một phase mồ côi của lần chạy bị huỷ còn sống thì phase sau báo `LOCKED` và dừng; khoá của tiến trình đã chết được lấy lại.
- **Giới hạn còn lại (verifier PR #36 vòng 2, LOW, cố ý chưa xử):**
  - *Huỷ run giữa `start`*: phase `start` mồ côi trên VPS thường vẫn đang đợi readiness, nên bước `rollback` báo `LOCKED` (không chạy đua). Sau đó phase mồ côi có thể chạy xong và để lại một bản **chưa qua acceptance** đang chạy; job vẫn đỏ. Rollback tự động **không** khôi phục được ca huỷ — người xem `state/history.log` rồi triển khai lại.
  - *Lấy lại khoá*: khoá không có file PID bị coi là cũ; về lý thuyết hai phase khởi động cách nhau vài micro-giây có thể cùng giữ khoá. Nhóm `concurrency: staging` của workflow đã chặn hai run song song, nên ca này thực tế không xảy ra.
  - *`docker rename` hỏng sau khi đã xoá container cũ*: bản mới chạy dưới tên `vip-staging-app-next`, `start` thoát 1, `rollback` xoá nó và báo `ROLLBACK_NOOP` → staging không còn bản nào chạy (thấy được, job đỏ) cho tới khi có người xử.
- Ảnh cũ và file env cũ được giữ trên VPS (không prune tự động) để rollback còn chạy được; dọn đĩa là việc của chủ VPS.

### Chuẩn bị VPS (chủ dự án làm một lần)

Runbook copy-chạy đầy đủ, tách lệnh MacBook / VPS, có script kiểm chỉ-đọc: **`VPS_STAGING_SETUP.md`** (CR-STG-004). Danh sách dưới đây là tóm tắt.


1. VPS Linux riêng (giả định Ubuntu 22.04/24.04 hoặc Debian 12, x86_64 — ảnh dựng trên runner `ubuntu-latest` amd64). **Không** dùng chung máy production.
2. Docker Engine (có `docker load`, `docker run`), `curl`, `bash`, `base64` (coreutils).
3. User deploy **không phải root**, thuộc nhóm `docker`, đăng nhập bằng khoá SSH (tạo cặp khoá riêng cho staging; khoá riêng → secret, khoá công khai → `~/.ssh/authorized_keys` của user này).
4. Thư mục ứng dụng (vd. `/srv/vip-staging`) do user deploy sở hữu, và file marker:
   ```bash
   printf 'vip-viettelpost staging\n' > /srv/vip-staging/STAGING_TARGET
   ```
5. PostgreSQL **16** riêng cho staging (cùng máy hoặc máy khác), CSDL + user riêng, **không** phải CSDL production. Nếu PG chạy trên chính VPS và lắng nghe trên host: dùng host `host.docker.internal` trong `DATABASE_URL` (container được thêm `host-gateway`), và cho phép dải mạng Docker trong `pg_hba.conf`; hoặc đặt `STAGING_DOCKER_NETWORK=host` (container dùng mạng host, lắng nghe `0.0.0.0:8000` trên VPS — phải chặn cổng 8000 bằng tường lửa; `STAGING_APP_PORT` bắt buộc là `8000`, khác thì hook dừng trước khi kết nối).
6. Reverse proxy HTTPS (Caddy/nginx…) cho domain staging → `http://127.0.0.1:8000` (hoặc `STAGING_APP_PORT`). Cổng 8000 không mở ra Internet.
7. Lấy host key để pin: `ssh-keyscan -t ed25519 -p <cổng> <host>` (với cổng khác 22, dòng sinh ra có dạng `[host]:cổng …` — dán nguyên như vậy) rồi **đối chiếu vân tay** với `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` chạy trên chính VPS trước khi dán vào secret `STAGING_SSH_KNOWN_HOSTS`.

### Lần deploy đầu tiên

1. Thêm secret/variable ở `GITHUB_ENVIRONMENT_STAGING.md` §B (method `vps`) và các secret ứng dụng §A; đặt `STAGING_DEPLOY_METHOD=vps`.
2. Kích hoạt workflow (mục 0 ở trên) với một SHA trên `develop`; duyệt job ở Environment `staging`.
3. Workflow: verify SHA → preflight → build ảnh → migrate (backup + upgrade) → start (kiểm SHA trên VPS) → readiness qua `STAGING_BASE_URL` → acceptance (có `--expected-sha`) → evidence. Hỏng ở bất kỳ bước nào sau `start` → workflow gọi `rollback`. Job chỉ xanh khi acceptance đạt.
4. Lần đầu chưa có `previous_sha`: nếu acceptance hỏng, `rollback` **dừng** bản hỏng và báo `ROLLBACK_NO_PREVIOUS_RELEASE` (job đỏ).
