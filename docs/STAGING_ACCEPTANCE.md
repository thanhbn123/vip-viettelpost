# STAGING ACCEPTANCE — pipeline, bằng chứng và luật verdict (CR-STG-001)

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
| `log_redaction` | log ứng dụng lấy **sau** các kiểm tra, **phải chứa `X-Request-ID` của lần chạy này** (`accept-<sha8>-<epoch>`, gắn vào mọi request) — chứng minh log đến từ đúng instance vừa phục vụ — và không chứa giá trị bí mật / JWT. Log rỗng, không lấy được, hoặc không có mã đó → `NOT_RUN` → **không** đạt |

**Luật verdict**
- `--kind staging`: **G15 = PASS** chỉ khi **cả 10** kiểm tra PASS trên URL `https://` staging thật; `NOT_RUN` không bao giờ tính là đạt. Verdict `ACCEPTED`.
- **G08 = PASS** chỉ khi có bằng chứng do job `vtp-dev-e2e` **của chính lần chạy** tạo ra (tải từ artifact chỉ khi job đó thành công), `sha` trong bằng chứng = SHA được triển khai, `base_url` = `https://partnerdev.viettelpost.vn`, và `authenticate`, `get_services`, `calculate_fee` đều PASS; file hỏng/giả → FAIL; không có bằng chứng → `BLOCKED_EXTERNAL_CREDENTIAL`. Test giả lập HTTP (13 test của script) **không** bao giờ đóng G08.
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
