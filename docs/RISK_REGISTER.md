# RISK REGISTER

Mức: CRITICAL / HIGH / MEDIUM / LOW. Chủ = ai phải hành động.

| Mã | Rủi ro | Mức | Tác động | Xử lý / trạng thái | Chủ |
|---|---|---|---|---|---|
| R-001 | Không có credential Viettel Post development (đo 2026-09-29: 0 biến môi trường `VTP_*`, 0 GitHub secret, 0 GitHub environment) | HIGH (chặn G08) | Chưa có bằng chứng API thật khớp tài liệu | G08 = `BLOCKED_EXTERNAL_CREDENTIAL`; mọi test dùng mock HTTP | Chủ dự án cấp credential dev qua secret |
| R-002 | Múi giờ `ORDER_STATUSDATE` không được tài liệu VTP nêu | MEDIUM | `occurred_at` rỗng tới khi cấu hình; thứ tự sự kiện dựa `received_at` | D-006: không đoán; bật `VTP_WEBHOOK_TIMEZONE` sau khi VTP xác nhận | Chủ dự án hỏi VTP |
| R-003 | Mã 104: bảng ghi "cuối", đoạn Lưu ý không liệt kê | LOW | Có thể xử lý sai trạng thái cuối | Theo đoạn Lưu ý (không cuối); ghi `STATUS_MAPPING.md` | Chủ dự án hỏi VTP |
| R-004 | Repo `thanhbn123/vip-viettelpost` đang PUBLIC | MEDIUM | Mã + tài liệu tích hợp công khai; lỡ commit bí mật là lộ ngay | Quét bí mật trong CI (G12); cân nhắc chuyển private | Chủ dự án quyết |
| R-005 | Nghĩa nghiệp vụ `ORDER_PAYMENT` 1–4 (ai trả cước/thu hộ) chưa chốt | MEDIUM | Không có mặc định; mỗi lệnh tạo đơn phải truyền | D-010 | Chủ dự án quyết |
| R-006 | Chưa có tra ID tỉnh/huyện/xã VTP theo tên | MEDIUM | Bên gọi phải tự truyền ID trong `provider_options` | D-003; cần xác minh API danh mục địa danh chính thức | Việc sau |
| R-007 | `getPriceAll` trả mảng trần theo mẫu tài liệu; chưa đo API thật | LOW | Parser có thể lệch nếu API thật bọc envelope | Báo `ViettelPostInvalidResponseError`, không nuốt; đo ở G08 | G08 |
| R-008 | Chưa có môi trường staging được cấp phép | HIGH (chặn G15) | Không thể STAGING PASS | G14 chuẩn bị đủ tài liệu/script; G15 = `STAGING ENVIRONMENT REQUIRED` | Chủ dự án cấp staging |
| R-009 | Nhiều kiện: không gửi kích thước cho VTP | LOW | Cước VTP tính theo khối lượng quy đổi có thể lệch | D-004; bên gọi có thể tách đơn | Theo dõi ở G08 |
| R-010 | Không có API tra cứu vận đơn VTP chính thức | MEDIUM | Trạng thái chỉ đến qua webhook; lỡ webhook thì không tự đối soát | D-019; theo dõi webhook `FAILED`/review | Hỏi VTP |
