# Review sẵn sàng develop → main (2026-10-02)

Phạm vi: **review để merge `develop` → `main`**. Không phải phê duyệt triển khai production — repo **chưa có** hợp đồng triển khai production (xem mục 7). Không merge `main`, không đụng production trong lượt này.

## 1. Mốc đo

| Mục | Giá trị |
|---|---|
| `main` | `3b89b367cf3bd57ac6021645ff15ae37958898f7` (commit khởi tạo) = merge-base |
| `develop` lúc bắt đầu | `4bb746a` (149 commit, 150 file, +19.437/−147 so với `main`) |
| Sửa trong lượt | CR-READY-001 (issue #55, PR #56 → `341bd6e`) + PR tài liệu này |
| Quy tắc `main` | `main-baseline` active: cấm xoá, cấm force push, bắt PR (0 duyệt), 5 check bắt buộc (`lint`, `test`, `postgres`, `image`, `rehearsal`), 0 bypass |

## 2. Bằng chứng gate

- **G08 PASS trên đúng `develop` cuối** — run 36990757808 (`26a5749`, 2026-10-06): evidence VTP `base_url` partnerdev, `auth_mode=login`, authenticate PASS (Login + ownerconnect thật), get_services PASS (8 dịch vụ), calculate_fee PASS (SCN 44.717 VND), không tạo đơn (create NOT_SAFE, cancel SKIPPED), không bước nào FAIL ⇒ thoả luật CR-STG-007 bằng nhánh "đăng nhập thật". Tạo + huỷ đơn thật đã chứng minh trước đó ở run 36978332181 (`aa5c4c0`: đơn thử 303296591832 tạo và huỷ). PASS 01/10 (run 36757608002) **đã rút lại**, không dùng làm căn cứ.
- **G15 PASS trên đúng `develop` cuối** — cùng run 36990757808: staging thật `https://cpn.viporder.vn`, `expected_sha` = `deployed_sha` = `26a5749`, migration head `shp_0004`, 10/10 kiểm tra PASS, `g15=PASS`, `g08=PASS`, `verdict=ACCEPTED`. `verdict` chỉ phụ thuộc G15; G08 phải đọc ở trường riêng.
- **Quan hệ SHA staging ↔ develop:** staging chạy đúng `26a5749` = HEAD `develop` (đo `/health/ready` 2026-10-06 23:50 +07).
- **Sự cố môi trường trước lượt chạy:** lần deploy đầu của run hỏng ở SSH (`Permission denied (publickey)`) vì `authorized_keys` của user `deploy` trên VPS staging bị ghi lại thủ công 2026-10-02 19:56 +07 (khoá CI bị gỡ). Chủ dự án thêm lại khoá 2026-10-06; job deploy chạy lại thành công. VPS staging nay **dùng chung** với dự án khác (cùng user `deploy`, cùng Caddy) — xem follow-up.

## 3. Phân loại phát hiện

Nguồn: 3 reviewer độc lập chỉ-đọc (diff/migration/rollback; webhook/COD/D-BIZ-001; bảo mật/cấu hình) + verifier PR #56.

**Đã sửa trong lượt (CR-READY-001):**
- MED bảo mật — `VTP_BASE_URL` không kiểm, không gắn `APP_ENV`: nay chỉ nhận URL dev/production chính thức; URL production đòi `APP_ENV=production`; `APP_ENV=production` thiếu/sai URL → dừng lúc khởi động; lỗi cấu hình không in secret.
- MED test — đường nối webhook thật (`get_vtp_webhook_processor`) chưa có test: thêm test 103 → 107 trên vận đơn có sẵn qua phụ thuộc thật (SQLite + PostgreSQL).

**BLOCKER cho merge develop → main:** không còn.

**CHẶN TRIỂN KHAI PRODUCTION (không chặn merge; phải xong trước production):**
1. Chưa có hợp đồng triển khai production: workflow, Environment `production`, secret/biến, máy chủ, CSDL, URL webhook, sao lưu/khôi phục, lưu giữ ảnh.
2. Quyết định còn mở đánh dấu "BLOCKS PRODUCTION": D-BIZ-002 (kế toán COD), D-SEC-001 (lưu giữ dữ liệu cá nhân), D-SEC-002 (rate limit / phân quyền key); D-VTP-001 (múi giờ) khuyến nghị.
3. VTP chưa xác nhận bằng văn bản nghĩa `ORDER_PAYMENT` 1–4 (D-BIZ-001 dựa trên nguồn bên thứ ba).
4. Đổi `WEBHOOK_SHARED_SECRET` (đã lộ ~20/64 ký tự đầu qua ảnh chụp) — và dùng secret riêng cho production.
5. Chưa diễn tập khôi phục CSDL từ bản dump.

**FOLLOW-UP (khoảng trống thật, hoãn được):**
- B-MED-1: luật D-BIZ-001 chỉ chặn COD + mã 1/4; COD + 2 và không-COD + 2/3/4 vẫn được nhận — chủ dự án xác nhận có cần chặn chặt hơn.
- B-MED-2: không đối chiếu `MONEY_COLLECTION` VTP trả về với COD đã gửi.
- B-MED-3: dòng `shipment_cod` không chuyển trạng thái khi huỷ / bị từ chối; ghi thu COD không kiểm trạng thái vận đơn (gắn D-BIZ-002).
- M1 (rollback): bản dump trước migration chỉ kiểm khác rỗng, chưa `pg_restore --list`.
- M3: job phát lại webhook (`app.jobs.replay_webhooks`) chưa có lịch chạy.
- M4: migration tạo index trên bảng lớn cần `CONCURRENTLY` (không ảnh hưởng CSDL mới).
- Chuỗi cung ứng: chưa bật Dependabot, chưa khoá phụ thuộc bắc cầu, ảnh gốc và Actions chưa ghim theo digest/SHA.
- Cách ly staging: VPS `160.22.170.20` (chọn riêng ngày 30/09) nay chạy thêm dự án khác dưới cùng user `deploy` (nhóm `docker` ≈ root) và cùng Caddy `vip-staging-caddy`; dự án khác có thể đọc/sửa env, CSDL, container staging. Không ảnh hưởng production; ảnh hưởng độ tin của bằng chứng staging về sau. **Chủ dự án quyết 2026-10-07: giữ dùng chung, chấp nhận rủi ro** (không tách VPS, không tách user). Hệ quả: bằng chứng staging chỉ đáng tin khi kèm kiểm `version`/SHA và marker `STAGING_TARGET` như hiện có; mọi sửa `~deploy/.ssh/authorized_keys` phải giữ khoá CI (lần 02/10 đã gỡ nhầm).
- Quy tắc `main`/`develop`: 0 lượt duyệt, `strict=false` (một người bảo trì); Environment `staging` cho admin bỏ qua.
- LOW: `/health/ready` công khai trả SHA + tên lớp lỗi; mặt nạ log chưa gồm mật khẩu trong `DATABASE_URL`; `.gitignore` chưa loại `*.pem`/`*.key`; fingerprint webhook khi thiếu ngày hash toàn bộ DATA; không có máy trạng thái đơn điệu khi ngày bằng nhau.

**KNOWN LIMITATION (đã đo, ghi rõ, không làm sai phạm vi hiện tại):**
- Chưa có E2E thật cho đơn **COD** (`ORDER_PAYMENT` 3) và chưa có E2E đối soát COD (G10 là sổ nhập tay theo thiết kế).
- Chưa có webhook VTP thật cập nhật một vận đơn **có sẵn** trong CSDL app (E2E tạo đơn ngoài app); đường này được test tự động HTTP + CSDL trên SQLite và PostgreSQL, kể cả qua phụ thuộc thật (CR-READY-001).
- Mới quan sát mã trạng thái thật 103 và 107; 19 mã khác ánh xạ theo bảng chính thức; mã lạ → không đổi trạng thái, `requires_review`, log WARNING, metric.
- Rollback chưa từng chạy thật với bản trước có đổi schema; khôi phục dump chưa diễn tập.

## 4. D-BIZ-001

Đúng quyết định: COD → 3, không COD → 1, **từ chối** COD > 0 kèm 1 hoặc 4 trước mọi lời gọi (`app/providers/viettel_post/provider.py`), không có mặc định (bên gọi truyền `provider_options.order_payment`), lỗi → 422. Test: COD 562000 / 1 / 0,01 với mã 1 và 4 bị từ chối, không request nào được gửi. **Giả định bên ngoài đã biết:** nghĩa mã chưa được VTP xác nhận bằng văn bản.

## 5. Migration

Chuỗi thẳng `shp_0001 → shp_0002 → shp_0003 → shp_0004`, một head; upgrade → downgrade base → upgrade chạy được (SQLite cục bộ; PostgreSQL 16 trong job CI `postgres`, `REQUIRE_POSTGRES=1`). `shp_0002` từ chối downgrade khi có sự kiện thiếu `occurred_at` (mặc định `VTP_WEBHOOK_TIMEZONE` rỗng).

## 6. Rollback

| Trường hợp | Phân loại |
|---|---|
| Lần phát hành production đầu (CSDL mới) | **UNSAFE / UNKNOWN** — chưa có hợp đồng triển khai, sao lưu, khôi phục production |
| Bản sau, không thêm migration | **APP_ONLY_SAFE** |
| Bản sau, có migration (kể cả tương thích ngược) | **APP_ONLY_CONDITIONAL** — `/health/ready` đòi revision = head nên rollback ứng dụng thuần sẽ not-ready; cần downgrade có kiểm soát |
| Phải lùi qua `shp_0002` khi đã có dữ liệu | **DB_RESTORE_REQUIRED** (khôi phục chưa diễn tập) |

## 7. Cấu hình production và tương đồng với staging

Không có workflow, Environment, secret hay biến production. Khác biệt **dự kiến**: `VTP_BASE_URL` = partner (production) thay partnerdev; credential VTP production; `APP_ENV=production` (nay bắt buộc đi cùng URL production); CSDL, tên miền, webhook production riêng; secret riêng. Khác biệt **chưa biết** (cần hợp đồng production): máy chủ/nền tảng, PostgreSQL production, proxy, cách nạp secret, sao lưu/khôi phục, lưu ảnh — **chặn triển khai production**, không chặn merge.

## 8. Bảo mật

PASS cho mã: không secret thật trong file theo dõi và toàn bộ lịch sử 150 commit (quét thay thế, gitleaks không có sẵn); `pip-audit` 0 lỗ hổng; API key băm SHA-256, so hằng thời gian, fail closed; chỉ `/health`, `/health/ready`, webhook không cần key; webhook so TOKEN hằng thời gian, thiếu secret → 503; SQL hằng; log che secret.

## 9. Kết luận

**READY_FOR_MAIN_REVIEW** (2026-10-06). `develop` `26a5749`: CI sau merge run 36990523295 5/5; staging thật đúng SHA (run 36990757808) G15 PASS + G08 PASS; verifier độc lập cuối chỉ-đọc **PASS** (10/10 khẳng định; `ruff` sạch, `pytest` 557 passed / 10 skipped cục bộ, phần PostgreSQL do job CI `postgres` phủ). Không còn blocker cho merge; 5 mục ở mục 3 **chặn production**, không chặn merge. Merge `develop` → `main` là quyết định của chủ dự án; lượt này **không** merge `main`, **không** triển khai production.
