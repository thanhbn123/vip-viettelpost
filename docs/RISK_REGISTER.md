# RISK REGISTER

Mức: CRITICAL / HIGH / MEDIUM / LOW. Chủ = ai phải hành động.

| Mã | Rủi ro | Mức | Tác động | Xử lý / trạng thái | Chủ |
|---|---|---|---|---|---|
| R-001 | Không có credential Viettel Post development (đo 2026-09-29: 0 biến môi trường `VTP_*`, 0 GitHub secret, 0 GitHub environment) | HIGH (chặn G08) | Chưa có bằng chứng API thật khớp tài liệu | G08 = `BLOCKED_EXTERNAL_CREDENTIAL`; mọi test dùng mock HTTP | Chủ dự án cấp credential dev qua secret |
| R-002 | Múi giờ `ORDER_STATUSDATE` không được tài liệu VTP nêu | MEDIUM | `occurred_at` rỗng tới khi cấu hình; thứ tự sự kiện dựa `received_at` | D-006: không đoán; bật `VTP_WEBHOOK_TIMEZONE` sau khi VTP xác nhận | Chủ dự án hỏi VTP |
| R-003 | Mã 104: bảng ghi "cuối", đoạn Lưu ý không liệt kê | LOW | Có thể xử lý sai trạng thái cuối | Theo đoạn Lưu ý (không cuối); ghi `STATUS_MAPPING.md` | Chủ dự án hỏi VTP |
| R-004 | Repo `thanhbn123/vip-viettelpost` đang PUBLIC | MEDIUM | Mã + tài liệu tích hợp công khai; lỡ commit bí mật là lộ ngay | Quét bí mật trong CI (G12); cân nhắc chuyển private | Chủ dự án quyết |
| R-005 | Nghĩa nghiệp vụ `ORDER_PAYMENT` 1–4 (ai trả cước/thu hộ) chưa chốt | MEDIUM | Không có mặc định; mỗi lệnh tạo đơn phải truyền | D-010. Verifier PR #6: `cod_amount > 0` hiện được gửi với mọi `ORDER_PAYMENT`; nếu có mã nghĩa là "không thu hộ" thì đơn COD có thể không thu tiền hàng → cần xác minh nghĩa 1–4 trên tài liệu chính thức rồi thêm luật chặn | Chủ dự án quyết |
| R-006 | Chưa có tra ID tỉnh/huyện/xã VTP theo tên | MEDIUM | Bên gọi phải tự truyền ID trong `provider_options` | D-003; cần xác minh API danh mục địa danh chính thức | Việc sau |
| R-007 | `getPriceAll` trả mảng trần theo mẫu tài liệu; chưa đo API thật | LOW | Parser có thể lệch nếu API thật bọc envelope | Báo `ViettelPostInvalidResponseError`, không nuốt; đo ở G08 | G08 |
| R-008 | Chưa có môi trường staging được cấp phép | HIGH (chặn G15) | Không thể STAGING PASS | G14 chuẩn bị đủ tài liệu/script; G15 = `STAGING ENVIRONMENT REQUIRED` | Chủ dự án cấp staging |
| R-009 | Nhiều kiện: không gửi kích thước cho VTP | LOW | Cước VTP tính theo khối lượng quy đổi có thể lệch | D-004; bên gọi có thể tách đơn | Theo dõi ở G08 |
| R-010 | Không có API tra cứu vận đơn VTP chính thức | MEDIUM | Trạng thái chỉ đến qua webhook; lỡ webhook thì không tự đối soát | D-019; theo dõi webhook `FAILED`/review | Hỏi VTP |
| R-011 | Quy tắc kế toán COD (ai sở hữu tiền, khi nào coi là tất toán, ai được điều chỉnh phí) chưa chốt | MEDIUM | G10 chỉ ghi số và suy trạng thái máy móc | Không mã hoá luật nghiệp vụ; ghi rõ trong `docs/FINANCE.md` | Chủ dự án quyết |
| R-012 | Quyền ghi đè trạng thái vận đơn bằng tay chưa chốt | LOW | Người vận hành chỉ ghi chú được, chưa sửa được trạng thái | Không làm endpoint ghi đè | Chủ dự án quyết |
| R-013 | Chưa có xác thực bên gọi API | ~~HIGH~~ → đóng khi G12 merge | Ai gọi được API là tạo/huỷ được vận đơn | G12: `X-API-Key` fail closed (D-033) | — |
| R-014 | Chưa có chính sách lưu giữ / xoá dữ liệu cá nhân (payload webhook, địa chỉ) | MEDIUM | Dữ liệu cá nhân tích luỹ không thời hạn | Cần quyết định nghiệp vụ/pháp lý; kỹ thuật sẵn sàng làm job xoá theo hạn | Chủ dự án quyết |
| R-015 | Chưa có rate limit, xoay vòng key tự động, phân quyền theo key | MEDIUM | Một key lộ = toàn quyền API tới khi gỡ khỏi `API_KEYS` | Gỡ key = xoá dòng khỏi secret + khởi động lại; đặt API sau proxy nội bộ ở staging | Việc sau |
