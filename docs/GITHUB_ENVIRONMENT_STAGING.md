# GitHub Environment `staging` — danh mục biến

Tên biến lấy **từ code** (`app/core/config.py` — pydantic-settings, không phân biệt hoa/thường; `migrations/env.py`; `scripts/smoke_test.py`; `scripts/vtp_dev_e2e.py`; `.github/workflows/staging.yml`). Không có giá trị thật nào trong tài liệu này. Đo ngày 2026-09-29 trước khi làm: repo chưa có Environment, secret hay variable nào; sau đó Environment `staging` được tạo **rỗng** (§C) — vẫn 0 secret, 0 variable.

**Cách thêm:** GitHub → repo → *Settings → Environments → staging* → *Environment secrets* / *Environment variables*. **Không** gửi giá trị qua chat, email, issue hay commit.

Chú thích cột: **TYPE** = SECRET (Environment secret) / VAR (Environment variable). **REQUIRED**: REQUIRED / OPTIONAL / ONE-OF. **EXPOSED TO APP?** = container ứng dụng đọc biến này. **SAFE TO LOG?** = được phép xuất hiện trong log/summary.

## A. Biến ứng dụng (container staging)

| NAME | TYPE | REQUIRED | PURPOSE | SOURCE | ROTATION | EXPOSED TO APP? | SAFE TO LOG? | DEFAULT? |
|---|---|---|---|---|---|---|---|---|
| `DATABASE_URL` | SECRET | REQUIRED | Kết nối PostgreSQL 16 staging, dạng `postgresql+psycopg://…` | Chủ dự án tạo DB + user riêng cho staging | Khi đổi mật khẩu DB / nghi lộ | Có (và Alembic đọc cùng tên) | **Không** | `sqlite:///./vip_shipping.db` — **không** dùng cho staging |
| `WEBHOOK_SHARED_SECRET` | SECRET | REQUIRED | So với `TOKEN` trong thân webhook VTP; thiếu → webhook 503 | Sinh ngẫu nhiên ≥ 32 ký tự, đăng ký cùng giá trị với VTP (dev) | Theo lịch + khi nghi lộ (phải đổi đồng thời ở VTP) | Có | **Không** | không có → fail closed |
| `API_KEYS` | SECRET | REQUIRED | Danh sách `<key_id>:<sha256 hex>` của key bên gọi API; thiếu → API 503, readiness 503 | `python -m app.tools.api_key <key_id>` trên máy tin cậy (in key thô 1 lần) | Thêm key mới → cập nhật bên gọi → gỡ key cũ | Có | Không (chỉ là băm, nhưng vẫn không log) | không có → fail closed |
| `VTP_TOKEN` | SECRET | ONE-OF (hoặc cặp dưới) | Token Partner **development** dùng nguyên (không tự làm mới) | Viettel Post cấp (môi trường dev) | Theo hạn VTP (ownerconnect: tài liệu ghi 1 năm) | Có | **Không** | không có |
| `VTP_USERNAME` | SECRET | ONE-OF (cùng `VTP_PASSWORD`) | Tài khoản Partner **development**; app gọi `Login` rồi `ownerconnect` | Viettel Post cấp | Theo chính sách VTP | Có | **Không** | không có |
| `VTP_PASSWORD` | SECRET | ONE-OF (cùng `VTP_USERNAME`) | Mật khẩu tài khoản trên | Viettel Post cấp | Theo chính sách VTP | Có | **Không** | không có |
| `VTP_BASE_URL` | VAR | OPTIONAL (khuyên đặt tường minh) | Nếu đặt thì phải là `https://partnerdev.viettelpost.vn` — workflow từ chối giá trị khác; để trống thì code dùng đúng URL dev | Hằng số (tài liệu VTP) | Không | Có | Có | `https://partnerdev.viettelpost.vn` |
| `VTP_TIMEOUT_SECONDS` | VAR | OPTIONAL | Timeout mỗi yêu cầu tới VTP | — | — | Có | Có | `20` |
| `VTP_WEBHOOK_TIMEZONE` | VAR | OPTIONAL — **để trống** | Múi giờ `ORDER_STATUSDATE`; chỉ đặt sau khi VTP xác nhận (D-VTP-001) | Viettel Post | — | Có | Có | trống |
| `WEBHOOK_MAX_BODY_BYTES` | VAR | OPTIONAL | Giới hạn thân webhook | — | — | Có | Có | `65536` |
| `API_MAX_BODY_BYTES` | VAR | OPTIONAL | Giới hạn thân API | — | — | Có | Có | `262144` |
| `DB_CONNECT_TIMEOUT_SECONDS` | VAR | OPTIONAL | Timeout kết nối PostgreSQL | — | — | Có | Có | `5` |
| `LOG_LEVEL` | VAR | OPTIONAL | Mức log | — | — | Có | Có | `INFO` |
| `LOG_FORMAT` | VAR | OPTIONAL (khuyên `json`) | `text` hoặc `json` | — | — | Có | Có | `text` |
| `PROVIDER_RETRY_MAX_ATTEMPTS` / `PROVIDER_RETRY_BASE_DELAY` / `PROVIDER_RETRY_MAX_DELAY` | VAR | OPTIONAL | Thử lại lệnh chỉ-đọc tới hãng (D-031) | — | — | Có | Có | `3` / `0.2` / `2.0` |
| `APP_ENV` | VAR | OPTIONAL | Chỉ để nhận diện; **code hiện không đọc** | — | — | Có | Có | `development` |

Tên **không** tồn tại trong code và không được thêm: `VTP_API_KEY`, `WEBHOOK_TOKEN`, `STAGING_DATABASE_URL`, `SECRET_KEY` — ứng dụng không đọc các tên đó.

## B. Biến dùng cho workflow / vận hành (không vào container)

| NAME | TYPE | REQUIRED | PURPOSE | SOURCE | ROTATION | EXPOSED TO APP? | SAFE TO LOG? | DEFAULT? |
|---|---|---|---|---|---|---|---|---|
| `STAGING_BASE_URL` | VAR | REQUIRED để deploy | URL HTTPS công khai của staging (smoke test, readiness, webhook) | Chủ dự án (DNS + proxy) | Khi đổi domain | Không | Có | không có → `STAGING_TARGET_MISSING` |
| `STAGING_DEPLOY_METHOD` | VAR | REQUIRED để deploy | Cách triển khai lên target. Giá trị hợp lệ duy nhất hiện có: **`vps`** (CR-STG-VPS) | Chủ dự án | — | Không | Có | không có / không có hook → `STAGING_TARGET_MISSING` |
| `SMOKE_API_KEY` | SECRET | REQUIRED để smoke | Key **thô** tương ứng một dòng trong `API_KEYS`, chỉ cho smoke test | Sinh cùng lúc với `API_KEYS` | Cùng `API_KEYS` | Không | **Không** | không có |
| `VTP_E2E_SCENARIO_JSON` | VAR | REQUIRED cho G08 | Kịch bản E2E (địa chỉ **thử**, ID địa danh VTP, gói hàng, `order_payment`) theo mẫu `scripts/vtp_dev_e2e.scenario.example.json` | Chủ dự án | — | Không | Có (chỉ dữ liệu thử, không dùng thông tin khách thật) | không có |
| `RUN_VTP_DEV_E2E` | VAR | OPTIONAL | `true` = khi kích hoạt bằng push `deploy/staging`, chạy thêm job E2E VTP dev (chỉ đọc) | Chủ dự án | — | Không | Có | rỗng → không chạy |
| `VTP_E2E_CREATE_TEST_ORDER` | VAR | OPTIONAL | `yes` = với push `deploy/staging`, E2E xin tạo+huỷ đơn thử (vẫn cần `VTP_E2E_ALLOW_CREATE=yes`) | Chủ dự án duyệt | Đặt lại rỗng sau khi thử | Không | Có | rỗng |
| `VTP_E2E_ALLOW_CREATE` | VAR | OPTIONAL | `yes` = cho phép E2E tạo **và huỷ ngay** 1 đơn thử ở VTP dev (cần thêm input `create_test_order`) | Chủ dự án duyệt | Đặt lại rỗng sau khi thử | Không | Có | rỗng → không tạo đơn |
| `DATABASE_URL_PSQL` | SECRET | OPTIONAL | Dạng libpq `postgresql://…` cho `psql`/`pg_dump` trước migration (method `vps` ghi nó vào file env; thiếu thì tự bỏ `+psycopg` khỏi `DATABASE_URL`) | Chủ dự án | Cùng `DATABASE_URL` | Có (file env) | **Không** | suy từ `DATABASE_URL` |
| `STAGING_SSH_HOST` | SECRET | REQUIRED khi method `vps` | Hostname/IP của **VPS staging** (không phải production) | Chủ dự án | Khi đổi máy | Không | **Không** | không có → `STAGING_TARGET_MISSING` |
| `STAGING_SSH_USER` | SECRET | REQUIRED khi method `vps` | User deploy **không phải root**, thuộc nhóm `docker` | Chủ dự án | — | Không | **Không** | `root` → bị từ chối |
| `STAGING_SSH_PRIVATE_KEY` | SECRET | REQUIRED khi method `vps` | Khoá SSH riêng (OpenSSH) chỉ dùng cho staging | Chủ dự án tạo cặp khoá mới | Theo lịch + khi nghi lộ | Không | **Không** | không có |
| `STAGING_SSH_KNOWN_HOSTS` | SECRET | REQUIRED khi method `vps` | Dòng `known_hosts` của VPS (pin host key; `StrictHostKeyChecking=yes`) — đối chiếu vân tay trên chính VPS trước khi dán | Chủ dự án | Khi cài lại máy | Không | Không nhạy nhưng đặt là secret cho gọn | không có |
| `STAGING_APP_DIR` | VAR | REQUIRED khi method `vps` | Thư mục trên VPS (tuyệt đối, ≥ 2 cấp, vd. `/srv/vip-staging`), phải chứa file marker `STAGING_TARGET` | Chủ dự án | — | Không | Có | không có |
| `STAGING_SSH_PORT` | VAR | OPTIONAL | Cổng SSH | — | — | Không | Có | `22` |
| `STAGING_APP_PORT` | VAR | OPTIONAL | Cổng trên `127.0.0.1` của VPS mà reverse proxy trỏ tới | — | — | Không | Có | `8000` |
| `STAGING_EXPECTED_HOSTNAME` | VAR | OPTIONAL (khuyến nghị) | `hostname` của VPS staging; khác → `STAGING_GUARD` | Chủ dự án | — | Không | Có | không kiểm |
| `STAGING_HOST_DENYLIST` | VAR | OPTIONAL (khuyến nghị) | Host/IP **production**, cách nhau bằng dấu phẩy; `STAGING_SSH_HOST` trùng → `PRODUCTION_GUARD` | Chủ dự án | Khi đổi máy production | Không | Có | rỗng |
| `STAGING_DOCKER_NETWORK` | VAR | OPTIONAL | Mạng Docker cho container (vd. `host` hoặc mạng chứa PG) | — | — | Không | Có | `bridge` |
| `STAGING_PG_TOOLS_IMAGE` | VAR | OPTIONAL | Ảnh có `psql`/`pg_dump` 16 (cấm `:latest`, được ghim `@sha256:`) | — | — | Không | Có | `postgres:16` |

## C. Bảo vệ Environment (khuyến nghị)

- *Deployment branches*: `develop` và `deploy/staging` (workflow còn tự kiểm SHA nằm trong `develop`). **Đã tạo 2026-09-29**: Environment `staging` rỗng (0 secret, 0 variable), required reviewer = `thanhbn123`, branch policy = `develop`, `deploy/staging`.
- *Required reviewers*: chủ dự án — mỗi lần chạy job dùng Environment `staging` phải được duyệt.
- Người duyệt là chủ dự án và được tự duyệt lần chạy của chính mình (`prevent_self_review=false`, admin được bỏ qua) — phù hợp khi chỉ có một người, cần xem lại khi thêm người.
- **Cổng thật sự là bước duyệt**: kiểm "SHA thuộc `develop`" nằm trong chính file workflow của commit được đẩy, nên ai có quyền ghi đều có thể đẩy commit sửa workflow lên `deploy/staging`. Hiện chỉ chủ dự án có quyền ghi. Ruleset cho `develop` và `deploy/staging` được định nghĩa dưới dạng code ở `.github/rulesets/` (CR-STG-002), áp bằng `scripts/github/apply_rulesets.py`; trạng thái áp thật ở `REPOSITORY_RULESETS.md`. **Ruleset không thay cho bước duyệt Environment:** check-run của một PR chưa merge cũng thoả điều kiện check, nên người có quyền ghi vẫn đẩy được commit chưa merge lên `deploy/staging` — bước duyệt mới là cổng thật.
- Không tạo Environment `production` trong phạm vi CR-SHP-001.
