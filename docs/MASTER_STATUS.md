# MASTER STATUS — VIP Shipping Gateway / Viettel Post

Bộ nhớ trạng thái của dự án (không dựa vào hội thoại). Cập nhật sau mỗi gate. Giờ theo +07:00.

**Cập nhật lần cuối:** 2026-10-01 — **G00–G15 PASS** (G08 = E2E Viettel Post development **chỉ đọc**; tạo đơn thật chưa chạy, chờ D-BIZ-001)
**`main`:** `3b89b367cf3bd57ac6021645ff15ae37958898f7` · **`develop`:** `8cd7d4bf8cedf626f364ac7df7efe5c0aeef8cf1` (sau merge PR #22; CI sau merge run 36539857970: lint, test 410 passed / 10 skipped, postgres 556 passed / 1 skipped, image — cả 4 success) · **`main`:** không đổi
**Migration head:** `develop` = `shp_0004_shipments_created_index`

| Gate | Phạm vi | Trạng thái | Nhánh | PR | HEAD SHA | CI | Tests | Blockers | Việc kế tiếp |
|---|---|---|---|---|---|---|---|---|---|
| G00 | Repository bootstrap | PASS | `main`/`develop` | — | `3b89b367cf3b` | success (run 36522312705, 36522312931) | 2 passed | — | — |
| G01 | Shipping core / domain | PASS — MERGED qua PR #6 | `feature/shp-core-domain` | #1 | `8515be2e8a35` | success | 63 passed | — | — |
| G02 | VTP auth / API client | PASS — MERGED qua PR #6 | `feature/vtp-api-client` | #2 | `d83ae97a2c0a` | success | 51 passed | — | — |
| G03 | Webhook / status mapper | PASS — MERGED qua PR #6 | `feature/vtp-webhook-status` | #3 | `a45b7fd6b692` | success | 80 passed | — | — |
| G04 | Database / migrations | PASS — MERGED qua PR #6 | `feature/shp-database` | #4 | `4df8ce7b699b` | success | 49 passed | — | — |
| G05 | Integration foundation | **PASS — MERGED** (merge `cc271b5`) | `integration/cr-shp-001` | #6 (issue #5) | `20f32b4a0630` | PR run 36528693788 success; sau merge `develop` run 36528952907 success | SQLite 290 passed; PG16 350 passed / 1 skipped | — | — |
| G06 | Application service / REST API | **PASS — MERGED** (merge `051e535`) | `feature/g06-application-api` | #8 (issue #7) | `1bf3302a5c59` | PR run 36530437942 success; sau merge `develop` run 36530744508 success | SQLite 325 passed; PG16 414 passed / 1 skipped | — | — |
| G07 | Durable webhook processing (nối vận đơn) | **PASS — MERGED** (merge `0fbdc2d`) | `feature/g07-webhook-apply` | #10 (issue #9) | `f635fa2be261` | PR run 36531821878 success; sau merge `develop` run 36532096484 success | SQLite 344 passed; PG16 452 passed / 1 skipped | — | lịch job replay → G14 |
| G08 | VTP sandbox / dev E2E | **PASS (chỉ đọc)** — run 36757608002 attempt 4 (SHA `c6ee0d6`), evidence `vtp-evidence-c6ee0d6…` trên **partnerdev**: authenticate, get_services (8 dịch vụ), calculate_fee (SCN 44.717 VND) PASS; acceptance `g08=PASS`. **Tạo/huỷ đơn chưa chạy** (cần D-BIZ-001 + cờ cho phép) | — | — | — | — | — | R-001 | chủ dự án thêm credential dev vào Environment `staging` |
| G09 | Shipment management / operational API | **PASS — MERGED** (merge `e828265`) | `feature/g09-operations` | #12 (issue #11) | `03231f7387cc` | PR run 36532374574 success; sau merge `develop` run 36532818524 success | SQLite 352 passed; PG16 468 passed / 1 skipped | — | — |
| G10 | COD / fee / reconciliation foundation | **PASS — MERGED** (merge `7acc3ba`) | `feature/g10-finance` | #14 (issue #13) | `c46def5e6fda` | PR run 36533633680 success; sau merge `develop` run 36533838889 success | SQLite 363 passed; PG16 490 passed / 1 skipped | R-011 (quy tắc kế toán) | — |
| G11 | Retry / resilience / observability | **PASS — MERGED** (merge `bb7aa4d`) | `feature/g11-resilience` | #16 (issue #15) | `c13b22b2980e` | PR success; sau merge `develop` run 36534685049 success | SQLite 378 passed; PG16 507 passed / 1 skipped | — | — |
| G12 | Security hardening | **PASS — MERGED** (merge `20c4981`) | `feature/g12-security` | #18 (issue #17) | `930b999f69ca` | PR run 36536141491 success (4 job); sau merge `develop` run 36536444054 success | SQLite 404 passed; PG16 535 passed / 1 skipped | — | — |
| G13 | PostgreSQL integration verification | **PASS — MERGED** (merge `baf827f`) | `feature/g13-postgres` | #20 (issue #19) | `476e1c7f0fb5` | PR run 36537880691 success (4 job); sau merge `develop` run 36538183266 success | SQLite 406 passed / 10 skipped (chỉ PG); PG16 549 passed / 1 skipped | — | — |
| G14 | Staging preparation | **PASS — MERGED** (merge `8cd7d4b`) | `feature/g14-staging` | #22 (issue #21) | `b9b5a12df698` | PR run 36539638446 success; sau merge `develop` run 36539857970 success | SQLite 410 passed / 10 skipped; PG16 556 passed / 1 skipped | — | — |
| G15 | Staging acceptance | **PASS** — staging thật https://cpn.viporder.vn, run 36750924951 (SHA `a6cadf7`), evidence `acceptance-evidence-a6cadf72…`: 10/10 kiểm PASS, verdict `ACCEPTED`; verifier độc lập PASS (xem `STAGING_ACCEPTANCE.md` *Lần nghiệm thu thật đầu tiên*) | — | — | — | — | — | R-008 | — |

## Drift đã biết của 4 PR (trước tích hợp) → trạng thái

Chi tiết từng dòng và test chứng minh: `docs/INTEGRATION_NOTES.md`.

- #1↔#2: `ViettelPostProvider`/`ShippingService` dùng `dict`; Address tên vs ID số; packages[] vs một tổng trọng lượng + `LIST_ITEM`; Money Decimal vs VND số nguyên; thiếu `product_type`/`price_table_type`/`order_payment` → **hoà giải ở G05**.
- #1↔#3: `ShipmentEvent.status` bắt buộc; giờ không múi giờ; provider enum/chuỗi; chữ ký `handle_webhook` → **hoà giải ở G05**.
- #3↔#4: kho chống trùng in-memory → **thay bằng `shipping_webhook_events` ở G05**.
- #1↔#4: provider enum ↔ `provider_id`; Money ↔ cột tiền; COD None ↔ 0; ánh xạ sự kiện; trạng thái → **hoà giải ở G05**.

## Blockers hiện tại (chỉ còn điều kiện bên ngoài)

| Blocker | Gate | Chủ dự án cần làm |
|---|---|---|
| R-001 Không có credential Viettel Post **development** — **đã có `VTP_TOKEN` dev (2026-10-01)**; tài khoản Login/ownerconnect chưa hợp lệ trên partnerdev | G08 | Cấp tài khoản/token dev của VTP vào kho bí mật (GitHub Environment `staging`), không gửi qua chat |
| R-008 Chưa có môi trường staging được cấp phép | G15 | Chỉ định máy/nền tảng staging + PostgreSQL 16 riêng + URL HTTPS cho webhook |

Quyết định nghiệp vụ đang chờ (không chặn STAGING READY): R-002 múi giờ `ORDER_STATUSDATE` + R-003 mã 104 (hỏi VTP), R-005/R-011 nghĩa `ORDER_PAYMENT` và quy tắc kế toán COD, R-004 repo PUBLIC, R-012 quyền ghi đè trạng thái, R-014 chính sách lưu giữ dữ liệu cá nhân, R-015 rate limit / xoay vòng key.

## PR đã merge vào `develop` (CR-SHP-001)

#1 · #2 · #3 · #4 (qua #6) · #6 G05 · #8 G06 · #10 G07 · #12 G09 · #14 G10 · #16 G11 · #18 G12 · #20 G13 · #22 G14. Mỗi PR: CI success đúng HEAD + verifier độc lập PASS (chi tiết `docs/VERIFICATION_LOG.md`).

## Staging continuation (2026-09-29)

Đo lại: `develop` `d580cc3`, `main` `3b89b36`, 0 PR mở, CI `develop` gần nhất success (run 36540309007), head `shp_0004_shipments_created_index`, 0 Environment / 0 secret / 0 variable trên repo, không có staging target được chỉ định. Quét bí mật cây + lịch sử (96 commit, mọi ref đã fetch; mẫu: khoá riêng, token GitHub/AWS/`sk-`/Slack, JWT không giả, URL có mật khẩu, gán biến bí mật của dự án) → **PASS** (chỉ placeholder và mật khẩu throwaway của CI).

Tài liệu mới: `STAGING_REQUIREMENTS.md`, `GITHUB_ENVIRONMENT_STAGING.md`, `STAGING_DEPLOYMENT.md`, `VTP_DEV_E2E.md`; quyết định còn mở trong `DECISIONS.md`. Workflow `staging.yml` (kích hoạt có kiểm soát: chạy tay hoặc push `deploy/staging`; Environment `staging`, kiểm SHA thuộc `develop`, test, build ảnh, deploy **dừng** với `STAGING_TARGET_MISSING` cho tới khi có target).

Verifier độc lập PR #25 lần 1 (HEAD `c567ccd`): **FAIL** — HIGH: `python scripts/vtp_dev_e2e.py` (lệnh trong workflow/tài liệu) lỗi `ModuleNotFoundError: app` → đổi sang `python -m scripts.vtp_dev_e2e`, thêm test subprocess chạy đúng lệnh. Kèm sửa: dịch vụ rỗng / bỏ qua tính cước không còn báo đạt, tạo đơn chỉ khi bước 1–3 PASS, kịch bản sai trả 2 và chỉ nêu tên trường, `persist-credentials: false`, tài liệu nhánh dispatch/ruleset/mâu thuẫn trạng thái Environment. Chi tiết `VERIFICATION_LOG.md`.

## Staging infrastructure closure (2026-09-29 21:54 +07)

Rebaseline: `develop` `2cbcff4` = `main` không đổi `3b89b36`, không drift; 0 PR mở; Environment `staging` 0 secret / 0 variable; 0 ruleset; `develop`/`main` không được bảo vệ. CR-STG-001 (issue #27): preflight chỉ-kiểm-có-mặt, deploy contract allowlist (0 method — `STAGING_TARGET_MISSING`), acceptance runner + luật verdict (`STAGING_ACCEPTANCE.md`), job CI `rehearsal` (container tạm, không bao giờ là bằng chứng staging), ảnh mang `APP_GIT_SHA`, readiness trả `version`. **G08 = BLOCKED_EXTERNAL_CREDENTIAL, G15 = BLOCKED_STAGING_INFRA. Chưa triển khai staging thật; chưa gọi Viettel Post; chưa kiểm webhook từ Internet.**

CR-STG-001 merged (PR #28 → `develop` `02600d049cb3c675fa53231cdec7025a44a83e49`; CI sau merge run 36594703999 5/5 gồm `rehearsal`). CR-STG-002 (ruleset as code) mở. **G08 = BLOCKED_EXTERNAL_CREDENTIAL, G15 = BLOCKED_STAGING_INFRA — không đổi; chưa có bằng chứng staging thật.**

CR-STG-002 merged (PR #30 → `develop` `5369d3b53f14a7319862225e4f84f4c55af45109`; verifier PASS tại `71367fa`, thêm test L-a tại `27594d1`; CI sau merge run 36597388635 5/5). Ruleset **đã áp** 2026-09-29 23:26:12 +07:00: `develop-baseline` (id 24193228) và `deploy-staging-baseline` (id 24193226), lần chạy thứ hai `SAME`; từ đây `develop` chỉ nhận thay đổi qua PR có đủ 5 check. `main` không có luật nào và không đổi (`3b89b36`). Chi tiết `REPOSITORY_RULESETS.md`. **G08/G15 không đổi.**

CR-STG-VPS (issue #35) merged 2026-09-30 (PR #36 → `develop` `0577bd9fde4cf87fbeb3de0b6be41b08c087a6fa`; verifier PASS vòng 2 tại `0096824`; CI sau merge run 36605661101 5/5). Chủ dự án chốt target staging = **VPS Linux riêng**; method `vps` (SSH + Docker, ảnh đúng SHA, marker `STAGING_TARGET`, PG16 + pg_dump trước migration, kiểm SHA trước khi chuyển, rollback chỉ ứng dụng) ở trạng thái **DESIGNED/TESTED — chưa REAL VPS VERIFIED**. Environment `staging` vẫn 0 secret / 0 variable → workflow vẫn dừng ở preflight. **G08 = BLOCKED_EXTERNAL_CREDENTIAL, G15 = BLOCKED_STAGING_INFRA — không đổi; chưa deploy VPS thật; `main` không đổi.**

CR-STG-004 (issue #38, 2026-09-30): đo 13:23:33 +07 — `develop` `5fccd7e` (CI run 36606194300 success), `main` `3b89b36` (4 luật), 0 PR mở, Environment `staging` **0 secret / 0 variable**, chưa có nhánh `deploy/staging` → chủ dự án chưa cấp VPS. Thêm runbook `VPS_STAGING_SETUP.md` (lệnh MacBook/VPS tách riêng, secret đi thẳng vào `gh secret set`) và `scripts/staging/vps/check-host.sh` (kiểm chỉ-đọc trên VPS) — **DESIGNED/TESTED, chưa chạy trên VPS thật**. D-BIZ-001 vẫn OPEN (bằng chứng mới ở `DECISIONS.md`). **G08 = BLOCKED_EXTERNAL_CREDENTIAL, G15 = BLOCKED_STAGING_INFRA — không đổi.**

**Staging thật lần đầu — 2026-10-01 00:44 +07.** Chủ dự án chọn VPS **riêng** (không dùng chung VPS production: user deploy trong nhóm `docker` ≈ root). VPS dựng theo `VPS_STAGING_SETUP.md` (host key + machine-id sinh lại vì trùng bản mẫu nhà cung cấp; `check-host.sh` @`670a6e7` → `RESULT: READY` cả HTTPS). Environment `staging`: 10 secret, 7 variable (chỉ đo tên). CR-STG-005 (PR #42, `a6cadf7`): preflight G15 đòi credential VTP. Run **36750924951** (push `deploy/staging` = `a6cadf7` = HEAD `develop`, chủ dự án duyệt 2 lần): verify/preflight/image/deploy SUCCESS, E2E VTP skipped. Deploy: ảnh đúng SHA (kiểm `APP_GIT_SHA`), sao lưu trước migration, PostgreSQL **16.15** (`server_version_num` 160015), migration từ CSDL rỗng tới `shp_0004_shipments_created_index`, `STARTED a6cadf7 (previous none)`. Acceptance `kind=staging`: 10/10 PASS (smoke 9/9, webhook 401/400/idempotent, 15 phản hồi + 27 dòng log không lộ secret) → `g15=PASS`, `verdict=ACCEPTED`. Đo trực tiếp trên VPS: app dùng `vip-staging-pg:5432/vip_staging`, `APP_ENV=staging`, `VTP_BASE_URL=https://partnerdev.viettelpost.vn`. **REAL STAGING DEPLOYED = YES; REAL POSTGRESQL 16 STAGING VERIFIED = YES** (container PG16 riêng trên VPS staging). **Chưa có:** G08 (E2E VTP dev chưa chạy — chờ D-BIZ-001 + `VTP_E2E_SCENARIO_JSON`), callback webhook thật từ VTP (chưa đăng ký URL), rollback chưa từng chạy thật (lần đầu, không có bản trước), khôi phục từ dump chưa thử. `main` không đổi `3b89b36`; production không đụng.

**G08 PASS (chỉ đọc) — 2026-10-01 16:35 +07.** CR-STG-006 (PR #45, `c6ee0d6`): job E2E trước đó không bao giờ chạy khi push vì `if:` cấp job không đọc được biến Environment — nay job `preflight` quyết định `run_e2e`. Kịch bản thử (`VTP_E2E_SCENARIO_JSON`, Environment `staging`): Hà Nội / Phường Cầu Giấy (1/49867) → TP.HCM / Phường Bến Thành (2/49236), 500 g, không COD, tên/SĐT thử, `order_payment` null — mã địa danh lấy từ danh mục V3 công khai của partnerdev. Ba lần đầu (`VTP_USERNAME`/`VTP_PASSWORD`) hỏng ở `authenticate`: partnerdev `/v2/user/Login` trả `Username or password is not valid!` (tài khoản không phải tài khoản Partner dev). Lần 4 dùng `VTP_TOKEN` lấy từ Bảng điều khiển partner2: run **36757608002 attempt 4**, push `deploy/staging` = `c6ee0d6` = HEAD `develop`, chủ dự án duyệt 3 cổng. VTP evidence (base `https://partnerdev.viettelpost.vn`, sha `c6ee0d6`): authenticate PASS, get_services PASS (BCN, NCOD, SCN, SHT, STK, VCN, VHT, VTK), calculate_fee PASS (SCN, 44.717 VND), create_shipment NOT_SAFE (không yêu cầu), cancel SKIPPED. Deploy: dump trước migration, PostgreSQL 160015, head `shp_0004`, `STARTED c6ee0d6 (previous a6cadf7)`. Acceptance: 10/10, **`g15=PASS`, `g08=PASS`, `verdict=ACCEPTED`**. Verifier độc lập chỉ-đọc: **G08 PASS (phạm vi chỉ đọc)**, STAGING ACCEPTANCE PASS; lưu ý: bước authenticate dùng token tĩnh (0 ms, không gọi mạng) — token được chứng minh gián tiếp qua getPriceAll/getPrice; G08 ở đây = 3 bước đọc theo `acceptance.py`, KHÔNG gồm tạo/huỷ đơn hay webhook như danh sách 6 bước của `VTP_DEV_E2E.md`. **Chưa có:** tạo/huỷ đơn thật (D-BIZ-001 OPEN), callback webhook thật từ VTP, đăng nhập bằng tài khoản Partner dev (chỉ token). `main` không đổi `3b89b36`; production không đụng.
