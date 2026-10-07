# PROJECT MASTER PLAN — VIP Shipping Gateway / Viettel Post

**Repo:** `thanhbn123/vip-viettelpost` · **CR:** CR-SHP-001 · **Đích của controller:** STAGING READY.
GitHub là nguồn chân lý; trạng thái sống ở `docs/MASTER_STATUS.md`, quyết định ở `docs/DECISIONS.md`, drift ở `docs/INTEGRATION_NOTES.md`, rủi ro ở `docs/RISK_REGISTER.md`.

## Luật cứng

- Không merge `develop → main`, không deploy production, không chạm CSDL production, không dùng credential production.
- Không force push, không viết lại lịch sử nhánh chung, không code trực tiếp trên `main`/`develop`.
- Hợp đồng VTP chỉ theo tài liệu Partner chính thức (`partner2.viettelpost.vn/document`); không đoán hành vi chưa được tài liệu hoá.
- Mọi thay đổi CSDL qua Alembic; không tạo/sửa schema lúc chạy.
- Mỗi PR có CI trên đúng HEAD; merge vào `develop` chỉ khi đủ cổng (xem dưới).

## Gate

| Gate | Phạm vi | Nguồn |
|---|---|---|
| G00 | Repository bootstrap | baseline `3b89b36` |
| G01 | Shipping core / domain | PR #1 |
| G02 | Viettel Post auth / API client | PR #2 |
| G03 | Webhook / status mapper | PR #3 |
| G04 | Database / migrations | PR #4 |
| G05 | Integration foundation: tích hợp #1–#4, hoà giải drift kiểu/hợp đồng/lưu trữ, webhook bền | `integration/cr-shp-001` |
| G06 | Application service + REST API trung lập với hãng | CR mới |
| G07 | Webhook bền nối trọn: TOKEN → claim → lưu thô → ánh xạ → cập nhật vận đơn → sự kiện → audit → ACK | CR mới |
| G08 | Viettel Post sandbox/dev E2E (cần credential) | CR mới |
| G09 | Quản lý vận đơn / API vận hành | CR mới |
| G10 | Nền COD / phí / đối soát | CR mới |
| G11 | Retry / resilience / observability | CR mới |
| G12 | Security hardening | CR mới |
| G13 | PostgreSQL integration verification | CR mới (một phần kéo sớm ở G05, D-016) |
| G14 | Staging preparation | CR mới |
| G15 | Staging acceptance (cần môi trường staging) | — |

## Cổng merge vào `develop`

HEAD PR ổn định · CI success đúng HEAD · toàn bộ test đạt · migration upgrade + downgrade đạt · không marker xung đột · không bí mật · không đổi schema lúc chạy · không gọi production · không blocker HIGH/CRITICAL chưa xử · `MASTER_STATUS` đã cập nhật · integration notes đủ.

## Dừng lại khi

Cần credential VTP thật · cần quyết định nghiệp vụ không suy ra được an toàn · tài liệu VTP mâu thuẫn không kiểm được · thiếu quyền GitHub · thiếu hạ tầng · migration rủi ro cao cần duyệt · sẵn sàng merge `develop → main` · sẵn sàng deploy production.
