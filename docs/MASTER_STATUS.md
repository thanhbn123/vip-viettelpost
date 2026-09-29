# MASTER STATUS — VIP Shipping Gateway / Viettel Post

Bộ nhớ trạng thái của dự án (không dựa vào hội thoại). Cập nhật sau mỗi gate. Giờ theo +07:00.

**Cập nhật lần cuối:** 2026-09-29 (G06 đã merge; G07 mở PR)
**`main`:** `3b89b367cf3bd57ac6021645ff15ae37958898f7` · **`develop`:** `051e5354a11cf72018a20f00161b1f770ad54fbc` (sau merge PR #8)
**Migration head:** `develop` = `shp_0003_active_order_guard`

| Gate | Phạm vi | Trạng thái | Nhánh | PR | HEAD SHA | CI | Tests | Blockers | Việc kế tiếp |
|---|---|---|---|---|---|---|---|---|---|
| G00 | Repository bootstrap | PASS | `main`/`develop` | — | `3b89b367cf3b` | success (run 36522312705, 36522312931) | 2 passed | — | — |
| G01 | Shipping core / domain | PASS — MERGED qua PR #6 | `feature/shp-core-domain` | #1 | `8515be2e8a35` | success | 63 passed | — | — |
| G02 | VTP auth / API client | PASS — MERGED qua PR #6 | `feature/vtp-api-client` | #2 | `d83ae97a2c0a` | success | 51 passed | — | — |
| G03 | Webhook / status mapper | PASS — MERGED qua PR #6 | `feature/vtp-webhook-status` | #3 | `a45b7fd6b692` | success | 80 passed | — | — |
| G04 | Database / migrations | PASS — MERGED qua PR #6 | `feature/shp-database` | #4 | `4df8ce7b699b` | success | 49 passed | — | — |
| G05 | Integration foundation | **PASS — MERGED** (merge `cc271b5`) | `integration/cr-shp-001` | #6 (issue #5) | `20f32b4a0630` | PR run 36528693788 success; sau merge `develop` run 36528952907 success | SQLite 290 passed; PG16 350 passed / 1 skipped | — | — |
| G06 | Application service / REST API | **PASS — MERGED** (merge `051e535`) | `feature/g06-application-api` | #8 (issue #7) | `1bf3302a5c59` | PR run 36530437942 success; sau merge `develop` run 36530744508 success | SQLite 325 passed; PG16 414 passed / 1 skipped | — | — |
| G07 | Durable webhook processing (nối vận đơn) | IN PROGRESS | `feature/g07-webhook-apply` | (mở) | xem PR | chờ | SQLite 340 passed; SQLite+PG16 cục bộ 444 passed / 1 skipped | — | CI → verifier → cổng merge |
| G08 | VTP sandbox / dev E2E | BLOCKED_EXTERNAL_CREDENTIAL | — | — | — | — | — | R-001 | chủ dự án cấp credential dev |
| G09 | Shipment management / operational API | OPEN | — | — | — | — | — | — | — |
| G10 | COD / fee / reconciliation foundation | OPEN | — | — | — | — | — | — | — |
| G11 | Retry / resilience / observability | OPEN | — | — | — | — | — | — | — |
| G12 | Security hardening | OPEN | — | — | — | — | — | — | — |
| G13 | PostgreSQL integration verification | PARTIAL (job CI PG kéo sớm ở G05, D-016) | — | — | — | — | — | — | — |
| G14 | Staging preparation | OPEN | — | — | — | — | — | — | — |
| G15 | Staging acceptance | BLOCKED — STAGING ENVIRONMENT REQUIRED | — | — | — | — | — | R-008 | chủ dự án cấp môi trường staging |

## Drift đã biết của 4 PR (trước tích hợp) → trạng thái

Chi tiết từng dòng và test chứng minh: `docs/INTEGRATION_NOTES.md`.

- #1↔#2: `ViettelPostProvider`/`ShippingService` dùng `dict`; Address tên vs ID số; packages[] vs một tổng trọng lượng + `LIST_ITEM`; Money Decimal vs VND số nguyên; thiếu `product_type`/`price_table_type`/`order_payment` → **hoà giải ở G05**.
- #1↔#3: `ShipmentEvent.status` bắt buộc; giờ không múi giờ; provider enum/chuỗi; chữ ký `handle_webhook` → **hoà giải ở G05**.
- #3↔#4: kho chống trùng in-memory → **thay bằng `shipping_webhook_events` ở G05**.
- #1↔#4: provider enum ↔ `provider_id`; Money ↔ cột tiền; COD None ↔ 0; ánh xạ sự kiện; trạng thái → **hoà giải ở G05**.

## Blockers hiện tại

- R-001 (HIGH): không có credential VTP dev → G08.
- R-008 (HIGH): chưa có môi trường staging → G15.
Cả hai là blocker **bên ngoài**, không chặn G05–G07, G09–G14.
