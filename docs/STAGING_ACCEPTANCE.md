# STAGING ACCEPTANCE — pipeline, bằng chứng và luật verdict (CR-STG-001)

> **Cập nhật 2026-10-01:** đã có lần nghiệm thu **thật** đầu tiên — G15 **PASS** (mục *Lần nghiệm thu thật đầu tiên* cuối file). Dòng trạng thái ngay dưới là lịch sử 29/09.

**Trạng thái (đo 2026-09-29 21:54 +07):** Environment `staging` có 0 secret, 0 variable; chưa có deploy method nào được cài → mọi lần chạy `staging.yml` dừng ở **preflight** với `STAGING_TARGET_MISSING`. **Chưa có staging thật nào được triển khai; chưa có bằng chứng staging nào.**

## Pipeline (`.github/workflows/staging.yml`)

| # | Job/bước | Việc | Dừng khi |
|---|---|---|---|
| 1 | `verify` | Commit là SHA 40 ký tự, nằm trên `develop`; ruff; pytest; một migration head | bất kỳ bước nào hỏng |
| 2 | `preflight` (Environment `staging`) | `scripts/staging/preflight.py --gate g15`: **chỉ kiểm có/không** từng secret (GitHub tự tính `secrets.X != ''` thành true/false — giá trị không tới script), kiểm `STAGING_BASE_URL` là `https://`, `STAGING_DEPLOY_METHOD` nằm trong allowlist; `--gate g08` chỉ báo sẵn sàng, không dừng | thiếu/không hợp lệ → in **tên** thiếu, dừng |
| 3 | `image` | `docker build --build-arg GIT_SHA=<sha>`; kiểm uid 10001, `APP_GIT_SHA` = SHA, import app; lưu ảnh làm artifact | hỏng |
| 4 | `vtp-dev-e2e` (tuỳ chọn) | Chỉ khi preflight G08 đủ **và** được bật: `python -m scripts.vtp_dev_e2e` tới **partnerdev**; bằng chứng gắn `sha` của lần chạy, lưu ngoài workspace. Được bật mà G08 chưa đủ → job **bị bỏ qua** (G08 = BLOCKED), không phải lỗi | E2E hỏng → **không deploy** |
| 5 | `deploy` → migrate | `scripts/staging/deploy.sh migrate` (hook của method) | hỏng → dừng, **không** bật ảnh mới |
| 6 | `deploy` → start | `deploy.sh start` chạy đúng ảnh của SHA | hỏng |
| 7 | readiness | `/health/ready` = 200, thử 30 lần (mỗi lần tối đa 10 s + nghỉ 10 s → khoảng 5–10 phút) | hỏng → rollback |
| 8 | acceptance | `python -m scripts.staging.acceptance --kind staging` trên URL staging thật (bảng dưới); log lấy bằng `deploy.sh logs` **sau** khi kiểm | verdict ≠ `ACCEPTED` → rollback |
| 9 | rollback | `deploy.sh rollback` khi `start` đã chạy (thành công **hoặc** hỏng giữa chừng) và job hỏng, bị huỷ hoặc quá giờ | — |
| 10 | bằng chứng | `acceptance-evidence.json` (artifact 90 ngày) + job summary: SHA, từng kiểm tra, G15, G08, verdict | luôn chạy |

Job có `timeout-minutes` (verify 20, preflight 5, image 20, e2e 10, deploy 45); `concurrency: staging`, không huỷ lần chạy đang dở.

## Kiểm tra acceptance (`scripts/staging/acceptance.py`)

| Kiểm tra | PASS khi |
|---|---|
| `health` | `/health` 200 |
| `readiness` | `/health/ready` 200, không kiểm con nào hỏng (CSDL, migration, webhook secret, API keys, credential VTP) |
| `deployed_sha` | `version` trong readiness = SHA được triển khai |
| `migration_head` | kiểm `migrations` của readiness `ok` (revision CSDL = head của mã) |
| `smoke` | 9/9 kiểm tra của `scripts/smoke_test.py` |
| `webhook_reachable` | POST URL webhook với `TOKEN` sai → 401 (URL tới được, xác thực hoạt động) |
| `webhook_malformed_rejected` | thân không phải JSON → 400 |
| `webhook_idempotency` | cùng một sự kiện tổng hợp (`ORDER_NUMBER=ACCEPT-<sha8>-<epoch>`, không khớp vận đơn nào) gửi 2 lần với `TOKEN` đúng → `ACCEPTED` rồi `DUPLICATE` (qua CSDL staging thật). **Tác dụng phụ:** 1 dòng webhook `IGNORED` trong CSDL staging |
| `no_secret_in_responses` | **mọi** phản hồi của lần chạy (kể cả 9 kiểm tra smoke, bắt qua event hook của client) không chứa giá trị bí mật — cả dạng đã giải mã URL của mật khẩu CSDL — hay chuỗi dạng JWT; chỉ báo **tên** biến |
| `log_redaction` | log ứng dụng lấy **sau** các kiểm tra, **phải chứa `X-Request-ID` của lần chạy này** (`accept-<sha8>-<epoch>-<16 hex ngẫu nhiên>`, gắn vào mọi request, không đoán trước được) — chứng minh log đến từ đúng instance vừa phục vụ — và không chứa giá trị bí mật / JWT. Log rỗng, không lấy được, hoặc không có mã đó → `NOT_RUN` → **không** đạt |

**Luật verdict**
- `--kind staging`: **G15 = PASS** chỉ khi **cả 10** kiểm tra PASS trên URL `https://` staging thật; `NOT_RUN` không bao giờ tính là đạt. Verdict `ACCEPTED`.
- **G08 = PASS** chỉ khi có bằng chứng do job `vtp-dev-e2e` **của chính lần chạy** tạo ra (tải từ artifact chỉ khi job đó thành công), `sha` trong bằng chứng = SHA được triển khai, `base_url` = `https://partnerdev.viettelpost.vn`, và `authenticate`, `get_services`, `calculate_fee` đều PASS; file hỏng/giả → FAIL; không có bằng chứng → `BLOCKED_EXTERNAL_CREDENTIAL`. Test giả lập HTTP (13 test của script) **không** bao giờ đóng G08.
- **Bổ sung CR-STG-007 (2026-10-02):** ngoài các điều kiện trên, G08 chỉ PASS khi Viettel Post **đã chấp nhận credential** trong chính lần chạy: `auth_mode=login` với `authenticate` PASS (Login + ownerconnect gọi mạng thật), **hoặc** `create_shipment` và `cancel_shipment` đều PASS. Chỉ có 3 bước đọc với token tĩnh (`auth_mode=static_token` hoặc thiếu `auth_mode`) → **`CREDENTIAL_NOT_VERIFIED`** (đã đo: token giả cũng làm 3 bước đọc PASS). Bất kỳ bước nào `FAIL` → `FAIL`. G08 không ảnh hưởng `verdict` (verdict chỉ theo G15).
- `--kind rehearsal` (job CI `rehearsal`, **không** có bước preflight, không có target: container tạm + PostgreSQL 16 service container của CI, secret sinh tạm): kết quả tốt nhất là `REHEARSAL_PASS`, G15 = G08 = `NOT_STAGING`. Chứng minh **cơ chế** pipeline chạy đúng, **không** phải bằng chứng staging.

## Webhook — hợp đồng đã kiểm bằng test tự động (không phải Internet thật)

| Hành vi | Test |
|---|---|
| `TOKEN` sai / thiếu → 401; chưa cấu hình → 503 | `tests/unit/test_webhook_vtp.py`, `tests/integration/test_auth.py` |
| Thân hỏng → 400; quá lớn (kể cả chunked) → 413 | `test_webhook_vtp.py`, `test_auth.py` |
| Trùng lặp / 6–8 luồng đồng thời → áp đúng 1 lần | `tests/integration/test_webhook_persistence.py`, `test_webhook_to_shipment.py` |
| Lỗi lưu trữ → 5xx, dòng `FAILED`, lần gửi lại xử lý lại | như trên |
| Không log `TOKEN`/dữ liệu cá nhân | `test_secret_and_pii_not_logged`, `test_database_errors_never_carry_sql_parameters` |
| HTTPS | bắt buộc ở staging (preflight + acceptance từ chối `http://`) |

Chưa làm: đăng ký webhook với Viettel Post và gọi thật từ Internet — cần staging host (G15).

## Lần nghiệm thu thật đầu tiên — 2026-10-01

| Mục | Giá trị |
|---|---|
| Run | `Staging` 36750924951, event `push` nhánh `deploy/staging`, attempt 1, duyệt Environment `staging` 2 lần (chủ dự án) |
| SHA | `a6cadf72d34383dc4f0a14c445e8d13a2de9c15b` = HEAD `develop` lúc chạy (`compare` = identical) |
| URL | https://cpn.viporder.vn (Let's Encrypt, hết hạn 29/12/2026) — VPS staging riêng, method `vps` |
| Deploy | env file lưu; ảnh `vip-shipping-gateway:staging-a6cadf7…` nạp + kiểm `APP_GIT_SHA`; dump trước migration; PostgreSQL 160015; migration → `shp_0004_shipments_created_index (head)`; `STARTED a6cadf7 (previous none)` |
| Acceptance (`acceptance-evidence-a6cadf72…`) | `health` 200 · `readiness` 200 không kiểm con nào hỏng · `deployed_sha` = SHA · `migration_head` · `smoke` 9/9 · webhook sai TOKEN → 401 · body hỏng → 400 · idempotency (200 ACCEPTED, 200 DUPLICATE) · 15 phản hồi không chứa secret · 27 dòng log sạch → **`g15=PASS`, `g08=BLOCKED_EXTERNAL_CREDENTIAL`, `verdict=ACCEPTED`** (do `acceptance.py` tính, không sửa tay) |
| Đo trực tiếp trên VPS | app → `vip-staging-pg:5432/vip_staging` (PostgreSQL 16.15, container riêng, không mở cổng); `APP_ENV=staging`; `VTP_BASE_URL=https://partnerdev.viettelpost.vn`; CSDL có 1 sự kiện webhook thử `IGNORED` (do kiểm idempotency, mỗi lần acceptance thêm 1 dòng) |
| Verifier độc lập | **STAGING ACCEPTANCE: PASS** (phạm vi G15) |

**Giới hạn (ghi rõ, không suy rộng):** kiểm tra `no_secret_in_responses`/`log_redaction` chỉ trong 15 phản hồi và 27 dòng log với các biến trong `ACCEPT_SCAN_VARS`; `kind=staging` không tự ghi IP/host đã phân giải (xác nhận qua DNS + đo trên VPS); credential VTP chỉ được kiểm **có mặt** (readiness), chưa gọi VTP (E2E bị bỏ qua); chưa có callback thật từ VTP; rollback và khôi phục từ dump chưa được chạy thật.

## Lần nghiệm thu thật thứ hai — G08 + G15 — 2026-10-01

| Mục | Giá trị |
|---|---|
| Run | `Staging` 36757608002 **attempt 4**, push `deploy/staging`, 3 cổng duyệt bởi chủ dự án |
| SHA | `c6ee0d6f7edb103348ec71f83453e8fe56c69cd6` = HEAD `develop` |
| VTP dev E2E (`vtp-evidence-c6ee0d6…`) | base `https://partnerdev.viettelpost.vn`; authenticate PASS (`VTP_TOKEN`); get_services PASS (8 dịch vụ); calculate_fee PASS (SCN, 44.717 VND); create_shipment NOT_SAFE; cancel SKIPPED |
| Deploy | dump trước migration; PostgreSQL 160015; `shp_0004 (head)`; `STARTED c6ee0d6 (previous a6cadf7)` — lần đầu có bản trước để rollback (rollback chưa phải chạy) |
| Acceptance (`acceptance-evidence-c6ee0d6…`) | 10/10 PASS → **`g15=PASS`, `g08=PASS`, `verdict=ACCEPTED`** |

Lịch sử attempt 1–3: `authenticate FAIL` (`ViettelPostBusinessError`) với `VTP_USERNAME`/`VTP_PASSWORD`; kiểm tay trên partnerdev: `Username or password is not valid!`. G08 theo luật repo (`acceptance.py`) chỉ đòi 3 bước đọc trên partnerdev cùng SHA — **không** phụ thuộc D-BIZ-001; tạo đơn thật vẫn chờ D-BIZ-001.

> **Đính chính 2026-10-02 (CR-STG-007):** `g08=PASS` của lần nghiệm thu thứ hai là **dương tính giả** — token giả cũng làm 3 bước đọc PASS. Lần tạo đơn (run 36900122982) cho `ViettelPostAuthError`. G08 hiện **BLOCKED_EXTERNAL_CREDENTIAL**; G15 PASS không đổi. Luật verdict G08 mới: đọc PASS **và** credential được VTP chấp nhận (Login, hoặc tạo + huỷ), nếu không → `CREDENTIAL_NOT_VERIFIED`.

## Lần nghiệm thu thật thứ ba — G08 thật + G15 — 2026-10-02

| Mục | Giá trị |
|---|---|
| Run | `Staging` 36978332181, push `deploy/staging`, 3 cổng duyệt bởi chủ dự án |
| SHA | `aa5c4c0471374895af4b28b126a97bd702619de6` = HEAD `develop` |
| VTP dev E2E | partnerdev, `auth_mode=login`; authenticate PASS (2021.8 ms); services PASS (8); fee PASS (SCN 44.717 VND); create PASS (303296591832); cancel PASS (attempts=2) — thoả luật CR-STG-007 cả hai nhánh |
| Deploy | dump trước migration; PostgreSQL 160015; `shp_0004 (head)`; `STARTED aa5c4c0 (previous c6ee0d6)` |
| Acceptance | 10/10 PASS → **`g15=PASS`, `g08=PASS`, `verdict=ACCEPTED`** |
| Webhook VTP thật | 103 + 107 cho mỗi đơn thử, lưu `IGNORED/SHIPMENT_NOT_FOUND`; bằng chứng người gửi gián tiếp (xem MASTER_STATUS) |
| Verifier độc lập | G08 PASS · STAGING ACCEPTANCE PASS |
