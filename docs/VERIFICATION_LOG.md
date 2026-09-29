# VERIFICATION LOG — verifier độc lập theo từng PR

Mỗi PR được một tác tử verifier **không viết mã đó** kiểm trên bản clone riêng, chỉ đọc, trước khi merge. Ghi: HEAD được kiểm, số test đo được, phát hiện, cách xử lý, kết luận.

## PR #6 — G05 Integration foundation

- Lần 1, HEAD `bcf34cf`: 287 passed (SQLite); 344 passed / 1 skipped (SQLite + PG 16). **FAIL**: 2 HIGH (race retry `FAILED` áp hai lần; `_record_failure` ghi đè lần giao thành công) + 1 MEDIUM (SQLite batch migration làm rỗng FK). Xử lý: D-020, D-021 (chi tiết `INTEGRATION_NOTES.md`).
- Lần 2, HEAD `20f32b4`: 290 passed; 350 passed / 1 skipped. **PASS**. 2 LOW mới ở `migrations/env.py` → sửa ở PR #8.

## PR #8 — G06 Application service / REST API

- Lần 1, HEAD `2c02b53`: 317 passed (SQLite); 401 passed / 1 skipped (PG riêng). **PASS**, kèm:

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | MEDIUM | Hai lệnh huỷ đồng thời gọi hãng hai lần | D-028: claim `operation_lock` bằng UPDATE có điều kiện → lệnh thứ hai 409 `operation_in_progress` |
| 2 | MEDIUM | Huỷ ghi đè `DELIVERED` do webhook đặt trong lúc gọi hãng (và giải phóng đơn) | D-028: ghi cuối có điều kiện `status = trạng thái đã đọc`; xung đột → giữ trạng thái, audit `PROVIDER_CANCELLED_AFTER_STATUS_CHANGE`, 409 |
| 3 | LOW | HTTP 401/403 của VTP bị coi là lỗi của bên gọi (422) | `ViettelPostHTTPAuthError` → 502 `provider_auth_failed` |
| 4 | LOW | Mọi `IntegrityError` lúc giữ chỗ bị báo trùng đơn | Chỉ index `uq_shipments_active_provider_order` mới là 409 |
| 5 | LOW | Phí lúc tạo không kiểm đơn vị tiền | Khác đơn vị → không lưu, log cảnh báo |
| 6 | LOW | Gọi CSDL đồng bộ trong handler async | Chấp nhận (chỉ ảnh hưởng thông lượng); xem G11 |
| 7 | LOW | Lỗi bất ngờ trả 500 thô | Handler chung: JSON `internal_error` + `request_id`, không lộ chi tiết |

Test hồi quy #1 và #2 **hỏng trên mã cũ** (2 failed) và đạt trên mã sửa.

- Lần 2, HEAD `1bf3302`: 325 passed; 414 passed / 1 skipped (PG riêng). **PASS** → merge PR #8 (`051e535`). Còn lại, sửa ở PR G07:

| # | Mức | Phát hiện | Xử lý (PR G07) |
|---|---|---|---|
| 1 | MEDIUM | Hãng đã nhận huỷ nhưng ghi CSDL hỏng → 500 chung, không audit, không log rõ | `PersistenceAfterProviderError` + log ERROR kèm mã vận đơn + audit `PROVIDER_CANCEL_NOT_RECORDED`; giữ khoá (không gửi huỷ lần hai ngay); webhook huỷ của VTP vẫn đưa vận đơn về `CANCELLED` |
| 2 | LOW | `asyncio.CancelledError` giữa lúc gọi hãng không nhả khoá | Bắt `BaseException` để nhả khoá rồi ném lại |
| 3 | LOW | Giá trị khoá luôn là `"CANCEL"` | Token riêng mỗi yêu cầu `CANCEL:<16 hex>`; ghi cuối so đúng token |
| 4 | LOW | Phản hồi 500 thiếu header `X-Request-ID` | Handler 500 tự đặt header |
| 5 | (ghi chú) | Downgrade về `base` trên PG hỏng FK khi đã có vận đơn | Đúng thiết kế: downgrade về base chỉ cho CSDL rỗng (dev/test); ghi vào rollback trong `DATABASE_SCHEMA.md` |

## PR #10 — G07 Durable webhook processing

- Lần 1, HEAD `fba138b`: 340 passed (SQLite); 444 passed / 1 skipped (PG riêng). Race thử thêm của verifier (5 sự kiện khác nhau đồng thời × 8 vận đơn; tạo + 2 job replay + 2 webhook đồng thời, mỗi thứ 3 lần, cả hai CSDL): sạch. **PASS**, kèm:

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| F1 | MEDIUM | Khoá so thứ tự hai loại (có múi giờ / chữ VTP) không bao giờ so với nhau → bật `VTP_WEBHOOK_TIMEZONE` sau đó thì sự kiện cũ kéo lùi trạng thái | Hãng có hàm khoá riêng (VTP) luôn so bằng khoá đó |
| F2 | MEDIUM | Khe hở D-027 chỉ job replay cứu được; job chưa có lịch | Thêm thước đo `unmatched_with_shipment` (phải về 0 sau mỗi lần chạy); lịch chạy là việc G14 |
| F3 | MEDIUM | Job replay bỏ qua dòng `FAILED` → mất sự kiện khi CSDL hỏng lâu hơn 5 lần thử của VTP | Job và `replay_unmatched` nhận cả `FAILED` |
| F4 | LOW | Huỷ: timeout/5xx/huỷ yêu cầu vẫn nhả khoá → gửi huỷ lần hai ngay | Chỉ nhả khi hãng từ chối; kết quả không rõ giữ khoá tới hết hạn, audit `PROVIDER_CANCEL_OUTCOME_UNKNOWN` |
| F5 | LOW | Webhook huỷ của VTP tới giữa lúc gọi huỷ → báo xung đột giả | Trạng thái đã `CANCELLED` = đồng thuận: 200 |
| F6 | LOW | `processed_at` ghi giờ nhận gốc khi replay | Ghi giờ xử lý thật |
| F7 | LOW | Đọc toàn bộ sự kiện cũ mỗi lần (O(n)) | Chấp nhận ở quy mô hiện tại |

Test F1 và F3 **hỏng trên mã cũ** (2 failed) và đạt trên mã sửa.
- Lần 2, HEAD `f635fa2`: 344 passed; 452 passed / 1 skipped. 60 phép thử race (retry `FAILED` trực tiếp × job replay, cả hai CSDL): mỗi sự kiện áp đúng 1 lần. **PASS** → merge PR #10 (`0fbdc2d`). Còn LOW L1 (job dừng cả lượt khi một khoá lỗi), L2 (replay trong luồng tạo không cô lập), L3 (thước đo bỏ sót `FAILED`/`RECEIVED`) → sửa ở PR G09, có test.

## PR #12 — G09 Operational API

- Lần 1, HEAD `03231f7`: 352 passed (SQLite); 468 passed / 1 skipped (PG riêng). Verifier tự thử savepoint (lỗi sau khi đã ghi một phần; transaction PG bị hỏng) — cả hai phục hồi đúng. **PASS** → merge PR #12 (`e828265`). Ghi nhận, không chặn:

| # | Mức | Phát hiện | Hướng xử lý |
|---|---|---|---|
| 1 | LOW | SQLite so `created_at` dạng chữ: dòng do `CURRENT_TIMESTAMP` của CSDL ghi (không phần lẻ giây) lệch biên lọc | Chỉ dòng chèn bằng SQL thô; ORM luôn ghi giờ Python. SQLite chỉ dùng dev/test |
| 2 | LOW | Thước đo `unmatched_with_shipment` có thể > 0 thoáng qua trong lúc hãng còn thử lại | Cảnh báo khi **giữ** > 0 qua nhiều lần đo, không theo một mẫu (`OBSERVABILITY.md`, G11) |
| 3 | LOW | Danh sách sắp theo `created_at` không có index; mỗi trang đếm toàn bộ | Index `(created_at, id)` ở G13 |
| 4 | INFO | Cờ xem xét tay không bao giờ tự hết | Đã ghi trong `API.md`; cần quyết định nghiệp vụ (R-012) |
| 5 | INFO | Test savepoint của PR không phủ ca ghi dở/transaction PG hỏng | Bổ sung test ở G13 |

## PR #14 — G10 COD / fee / reconciliation

- Lần 1, HEAD `d1eee6a`: 358 passed (SQLite); 480 passed / 1 skipped (PG riêng). 20 luồng `add_fee` đồng thời: `actual_fee` = tổng dòng ở cả hai CSDL. **FAIL**:

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | HIGH | Nộp lần hai sau `REMITTED` giữ `REMITTED` trong khi số nộp ≠ số thu | `REMITTED` chặn nộp tiếp (409); trạng thái suy lại từ ba con số sau mỗi lần ghi |
| 2 | MEDIUM | Số nộp vượt số thu; số thu hạ dưới số đã nộp | 422 cả hai chiều |
| 3 | LOW | Tổng phí vượt `NUMERIC(18,2)` → 500 | Bọc thành `FinanceError` → 422 |
| 4 | LOW | Đối soát COD trên vận đơn không COD coi dự kiến = 0 | 422, như các thao tác COD khác |
| 5 | INFO | COD vận đơn huỷ; thời điểm tương lai; chung mã audit điều chỉnh/chốt | Ghi vào `FINANCE.md` / R-011 |

Test #1 và #2 **hỏng trên mã cũ** (2 failed) và đạt trên mã sửa.
- Lần 2, HEAD `c46def5`: 363 passed; 490 passed / 1 skipped. 30 luồng thu/nộp COD trộn: trạng thái luôn khớp số, nộp ≤ thu. **PASS** → merge PR #14 (`7acc3ba`). Còn LOW: số 0 nhập nhầm rồi nộp 0 thành `REMITTED` cuối cùng (sửa qua đối soát; có cho nộp 0 hay không là R-011).

## PR #16 — G11 Retry / resilience / observability

- Lần 1, HEAD `c13b22b`: 378 passed (SQLite); 507 passed / 1 skipped (PG riêng). **PASS** → merge PR #16 (`bb7aa4d`). Sửa ở PR G12:

| # | Mức | Phát hiện | Xử lý (PR G12) |
|---|---|---|---|
| 1 | MEDIUM | Readiness treo ~75 s khi máy CSDL im lặng (không `connect_timeout`) | `connect_timeout` 5 s cho PostgreSQL (`DB_CONNECT_TIMEOUT_SECONDS`) |
| 2 | MEDIUM | Log JSON bỏ mất traceback | Trường `exc` (đã che) |
| 3 | LOW/MED | Lớp che bí mật không che traceback | Che `exc_text` và `stack_info` |
| 4 | LOW | `__getattr__` đệ quy khi copy/unpickle | Chặn tên `inner` |
| 5 | LOW | Log lỗi 500 có `request_id` = `-` | Handler đặt lại contextvar khi ghi log |
| 6 | LOW | Độ trễ xấu nhất ~60,6 s khi thử lại | Ghi trong `OBSERVABILITY.md` |
| 7 | LOW | Logger uvicorn không qua lớp che | Ghi giới hạn trong `OBSERVABILITY.md` |
| 8 | LOW | Lỗi cây migration → 500 thay vì 503 | Bắt trong readiness; head được cache |

## PR #18 — G12 Security hardening

- Lần 1, HEAD `2ed2c98`: 398 passed (SQLite); 529 passed / 1 skipped (PG riêng); ruff sạch; pip-audit 0. Thử vượt xác thực (gạch chéo cuối, `//`, mã hoá URL, method override, HEAD/OPTIONS, header trùng/hoa/khoảng trắng): không vượt được. **PASS**, kèm:

| # | Mức | Phát hiện | Xử lý (trước khi merge) |
|---|---|---|---|
| 1 | MEDIUM | Thân `chunked` không có Content-Length vượt giới hạn, kể cả khi **chưa xác thực** (50 MB đọc hết, RSS 106→242 MB) | Middleware ASGI ngoài cùng đếm byte thật, trước định tuyến/xác thực; test hỏng trên mã cũ |
| 2 | MEDIUM | `/docs`, `/redoc`, `/openapi.json` công khai, trái `SECURITY.md` | Tắt UI; `/openapi.json` sau API key |
| 3 | LOW | `.dockerignore` chỉ khớp ở gốc | Mẫu `**/`; CI cài mồi cả ở `app/.env`, `migrations/decoy.db` |
| 4 | LOW | Kiểm tra CI của ảnh dễ vỡ (`!` + errexit) | So sánh tường minh `test -z`, `set -euo pipefail` |
| 5 | LOW | `API_KEYS` sai không chặn khởi động | Kiểm lúc nạp app → không khởi động |
| 6 | LOW | "`hide_parameters` mọi engine" nói quá | Thêm cho Alembic CLI; sửa câu chữ phạm vi |
| 7 | LOW | Tripwire bỏ sót nhiều loại, cho qua cả dòng có chữ "test" | Xét trên chính chuỗi; thêm URL có mật khẩu và các biến bí mật của dự án; test tự kiểm |
| 8 | LOW | Phản hồi 500 thiếu header bảo mật | Thêm vào handler 500 |
| 9 | LOW/INFO | Docstring che API key sai; file DB tạm của test để lại; ảnh gốc chưa ghim digest; cảnh báo `httpx2` của Starlette | Sửa docstring; dọn thư mục tạm cuối phiên test; ghi chưa làm |
- Lần 2, HEAD `930b999`: 404 passed; 535 passed / 1 skipped. Uvicorn thật, socket thô: 50 MB chunked (có/không key) bị cắt 413 ngay sau chunk 1 MB đầu; RSS cả lượt thử +9,6 MB (trước sửa: +135 MB cho một yêu cầu). **PASS** → merge PR #18 (`20c4981`). LOW còn lại, sửa ở PR G13: tripwire bỏ sót dạng chữ thường/YAML (thêm `re.IGNORECASE`, `[=:]`); self-test chép lại logic lọc (tách hàm `scan`/`is_real_secret` dùng chung); 413 thiếu vài header (thêm); CI che lỗi `grep` (phân biệt mã 1 và >1). Còn chấp nhận: giá trị bí mật tự chứa chữ "test" vẫn lọt tripwire; 413 không có `X-Request-ID` (chạy ngoài middleware request id).

## PR #20 — G13 PostgreSQL verification

- Lần 1, HEAD `789c1fd`: 405 passed / 10 skipped (SQLite); 547 passed / 1 skipped (PG riêng). Thử đột biến M1–M7 (index sai cột/tên, downgrade rỗng, vị từ thừa, bỏ `postgresql_where`, CHECK nới, đổi kiểu tiền): đều bị bắt. **PASS**, kèm:

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | MEDIUM | Test savepoint không chạy qua ứng dụng: bỏ savepoint trong `shipping_app.py` (M8) mà suite vẫn xanh | Test mới qua đường thật (`test_replay_failing_inside_the_database_does_not_lose_the_created_record`); đột biến M8 nay **hỏng trên PG** |
| 2 | LOW | Tripwire có vài âm tính giả mới (giá trị chứa `,`/`)`, `<...>` áp mọi mẫu) | Chấp nhận, ghi lại; tripwire không phải công cụ quét đầy đủ |
| 3 | LOW | Test vị từ chỉ tìm chuỗi | So đúng tập `{DRAFT, CANCELLED}` |
| 4 | LOW | Header 413 là bản chép tay | Dùng chung `SECURITY_HEADERS`; test kiểm đủ |
| 5 | LOW | Test PG có thể lặng lẽ bị bỏ qua nếu CI mất biến | `REQUIRE_POSTGRES=1` trong job `postgres` → thiếu URL là hỏng |

## PR #22 — G14 Staging preparation

- Lần 1, HEAD `9f54ed7`: 408 passed / 10 skipped; 552 passed / 1 skipped. Chạy thật uvicorn + PG 16.15 theo đúng runbook: migration `current`/`history`/`upgrade head` → `shp_0004 (head)`; smoke 9/9 (exit 0) khi cấu hình đúng, exit 1 khi thiếu `API_KEYS` (5/9) hoặc `WEBHOOK_SHARED_SECRET` (7/9); không đổi dòng nào trong 11 bảng; readiness 503 khi CSDL ở `shp_0003`. **PASS**, kèm (sửa trước merge):

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| M1 | MEDIUM | `pg_dump "$DATABASE_URL_PSQL"` dùng biến không định nghĩa → chưa đặt thì dump nhầm CSDL mặc định mà vẫn báo thành công | Định nghĩa biến (dạng libpq), `: "${…:?}"`, `set -euo pipefail`, kiểm bản dump bằng `pg_restore --list` |
| M2 | MEDIUM | Lùi mã và schema gắn nhau (readiness đòi đúng head) mà runbook không nói | Bảng thứ tự rollback: ngưng tải → sao lưu → lùi schema → ảnh cũ → ready → mở tải |
| L1 | LOW | Điều kiện từ chối downgrade thiếu `occurred_at` | Ghi đúng; nêu rõ thực tế không lùi được qua shp_0002 khi có dữ liệu |
| L2 | LOW | `-x db_url=` lộ mật khẩu trong `ps` | Dùng biến môi trường `DATABASE_URL` |
| L3 | LOW | Key thô in ra màn hình / vào lịch sử shell | Cảnh báo; nhập key bằng `read` không vang |
| L4 | LOW | Readiness 200 khi thiếu `API_KEYS` | Thêm kiểm `api_keys` vào readiness |
| L5 | LOW | Access log uvicorn không phải JSON | Ghi rõ, gợi ý `--no-access-log` |
| L6 | LOW | `APP_ENV` không có tác dụng | Ghi rõ trong bảng biến |
| L7 | LOW | Kiểm "không lộ nội bộ" của smoke chỉ phủ 404 | Ghi rõ phạm vi |
| L8 | LOW | Thước đo không có lệnh chạy; smoke chạy từ đâu | Job in thước đo và thoát mã 3 khi > 0; hướng dẫn chạy smoke từ checkout |
- Lần 2, HEAD `c863d8d`: 409 passed / 10 skipped; 554 passed / 1 skipped. Khối §4 chạy nguyên văn: thiếu biến → dừng (bash và zsh), đủ biến → dump được `pg_restore --list` nhận, `current` = `shp_0004 (head)`; readiness 503 khi thiếu `API_KEYS`; §5 đúng (D-015 từ chối như mô tả). **FAIL**: H1 **HIGH** — `python -m app.jobs.replay_webhooks` luôn lỗi `NameError` (khối `__main__` đứng trước hàm mới gọi) → mọi lần chạy theo lịch thoát 1. Sửa: đưa khối `__main__` xuống cuối; test chạy đúng lệnh `-m` bằng subprocess (hỏng trên mã cũ) + test mã thoát 3. LOW: §4 chỉ an toàn khi chạy dạng file (ghi rõ); dump ghi ngoài repo + `.gitignore` chặn `*.dump`, ưu tiên `~/.pgpass`; thêm `DATABASE_URL_PSQL` vào bảng biến.

## PR #25 — Staging continuation

- Lần 1, HEAD `c567ccd`: 417 passed / 10 skipped; 563 passed / 1 skipped. 14 biến thể URL production đều bị từ chối, 0 yêu cầu gửi đi; 8 đột biến, 7 bị bắt. **FAIL**:

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | HIGH | `python scripts/vtp_dev_e2e.py` không import được `app` → job G08 luôn hỏng | `python -m scripts.vtp_dev_e2e` ở workflow/tài liệu; test subprocess chạy đúng lệnh (và lệnh smoke) |
| 2 | MEDIUM | Dịch vụ rỗng + không có mã dịch vụ → thoát 0 mà chưa gọi tính cước; tạo đơn vẫn thử khi bước trước hỏng | Dịch vụ rỗng = FAIL; bước chỉ-đọc không PASS = run hỏng; tạo đơn chỉ khi 1–3 PASS |
| 3 | MEDIUM | Dispatch từ `main` bị Environment từ chối | Tài liệu + chú thích workflow: chọn `develop` |
| 4 | MEDIUM (cấu hình) | Kiểm "thuộc develop" nằm trong workflow của commit được đẩy; repo không có ruleset | Ghi rõ bước duyệt là cổng thật; khuyến nghị ruleset (việc của chủ dự án) |
| 5 | LOW | Kịch bản sai → traceback có giá trị (SĐT) trong log, mã thoát 1 | Kiểm kịch bản trong `load_scenario`, chỉ nêu tên trường, thoát 2 |
| 6 | LOW | Không test vắng dữ liệu cá nhân ở bằng chứng tạo đơn | Thêm test |
| 7 | LOW | Tài liệu tự mâu thuẫn (Environment đã tạo/chưa, nhánh, danh sách biến, "chạy tay", `VTP_BASE_URL` REQUIRED) | Sửa |
| 8 | LOW | "Dùng được ngay" quá rộng (commit cũ không có `staging.yml`) | Ghi rõ từ commit merge PR #25 trở đi |
| 9 | LOW | `checkout` giữ token; tự duyệt | `persist-credentials: false`; ghi rõ tự duyệt |

## PR #28 — CR-STG-001 staging acceptance pipeline

- Lần 1, HEAD `29c4524`: 441 passed / 10 skipped (SQLite); 594 passed / 1 skipped (PG riêng); CI rehearsal 10/10 PASS (`REHEARSAL_PASS`). **PASS**, kèm (sửa trước merge):

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| M1 | MEDIUM | Log rỗng (`--logs-cmd true`) → `log_redaction` PASS → **ACCEPTED** | Log rỗng → NOT_RUN; log phải chứa `X-Request-ID` của lần chạy (gắn vào mọi request) |
| M2 | MEDIUM | Không quét 9 phản hồi smoke (gồm danh sách vận đơn, `/metrics`) | Bắt mọi phản hồi qua event hook của client |
| M3 | MEDIUM | G08 PASS từ file giả/cũ; file `vtp-evidence.json` commit vào repo sẽ được dùng khi E2E bị bỏ qua | Bằng chứng gắn `sha`; tải ngoài workspace, chỉ khi job E2E thành công; file hỏng → FAIL |
| M4 | MEDIUM | `start` hỏng giữa chừng / huỷ / quá giờ → không rollback | Rollback khi `start` đã chạy và job hỏng hoặc bị huỷ; hợp đồng: `start` không được bỏ dở, `rollback` an toàn khi không có gì đổi |
| L1 | LOW | Readiness trả kiểu lạ → crash không có bằng chứng; file E2E hỏng làm crash | Bắt lỗi, ghi FAIL |
| L2 | LOW | Chỉ quét mật khẩu CSDL dạng mã hoá URL | Quét cả dạng đã giải mã |
| L3 | LOW | Rehearsal có thể báo G08 | Rehearsal luôn G08 = NOT_STAGING |
| L4 | LOW | Tài liệu: "5 phút", tên bước rehearsal, E2E bị bỏ qua | Sửa câu chữ |
| L5 | LOW | Ghi chú D-BIZ-001 có giờ không chính xác | Ghi đúng mốc đo được |
| L6 | LOW | Giá trị có xuống dòng chèn dòng env; userinfo trong URL | Từ chối xuống dòng; acceptance từ chối URL có userinfo |
- Lần 2, HEAD `7d1bc6c`: 447 passed / 10 skipped; 604 passed / 1 skipped; CI rehearsal 10/10 (log có request id, 15 phản hồi được quét). **FAIL**: H1 **HIGH** — `scripts/vtp_dev_e2e.py` không ghi `sha` (bước sửa trước **không áp được** mà không bị phát hiện), nên bằng chứng E2E thật luôn cho G08 = FAIL; test chỉ đạt nhờ fixture tự thêm `sha`. Sửa: script ghi `sha` từ `VTP_E2E_SHA`; test đầu-cuối đưa **đúng file script sinh ra** vào acceptance (hỏng khi bỏ dòng ghi `sha`). LOW: rollback thêm trường hợp `start` bị huỷ giữa chừng; file env chỉ mở sau khi kiểm xong mọi giá trị; mã request id thêm phần ngẫu nhiên 16 hex (không đoán trước được).
- Lần 3, HEAD `638bee0`: 448 passed / 10 skipped; 606 passed / 1 skipped; H1 tái hiện với file thật của script: có `VTP_E2E_SHA` → G08 PASS, không có / sai → FAIL; đột biến bỏ dòng `sha` bị test bắt. **PASS** → merge PR #28 (`02600d0`), CI sau merge 5/5.
- PR #30 lần 1 (HEAD `af3dec9`): 451 passed / 10 skipped; dry-run CREATE ×2; JSON hợp lệ, áp không phá luồng hiện tại. **PASS**, kèm M1 (bộ so lệch luôn báo UPDATE vì trường mặc định của GitHub → chỉ so trường khai báo, có test), M2 (tài liệu nghe như đã áp → ghi rõ chưa áp), LOW: in lỗi GitHub khi API hỏng, phân trang, test kiểm cả 5 job + cấm `name:`, ghi rõ ruleset không thay bước duyệt, cách gỡ kẹt.
