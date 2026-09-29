# Status mapping

VIPORDER canonical statuses:

- DRAFT
- READY_TO_CREATE
- CREATED
- READY_TO_PICK
- PICKED
- IN_TRANSIT
- OUT_FOR_DELIVERY
- DELIVERED
- DELIVERY_FAILED
- RETURNING
- RETURNED
- CANCELLED

Không điền mã trạng thái Viettel Post bằng suy đoán. Chỉ cập nhật bảng mapping sau khi đối chiếu tài liệu chính thức.

---

## Viettel Post → canonical

**Nguồn chính thức:** <https://partner2.viettelpost.vn/document/webhook>, mục *"Bảng danh sách trạng thái"* và đoạn *"Lưu ý"* về trạng thái cuối. Đối chiếu ngày 29/09/2026.
(`partner.viettelpost.vn` chuyển hướng 301 sang `partner2.viettelpost.vn`.)

**Mã nguồn:** `app/providers/viettel_post/status_mapper.py`.

`ORDER_STATUS` trong tài liệu là kiểu **Integer**. Bộ ánh xạ chuẩn hoá về chuỗi số thập phân (`501`) và giữ nguyên giá trị gốc trong payload lưu trữ.

### Bảng ánh xạ (21 mã chính thức)

| Mã VTP | Tên chính thức | Mô tả chính thức | Canonical | Cuối? | Ghi chú |
|---|---|---|---|---|---|
| 101 | Viettel Post hủy lấy hàng | Viettel Post hủy lấy hàng | `CANCELLED` | Y | |
| 102 | Lấy hàng thất bại | Lấy hàng thất bại | — | | Không có canonical "lấy hàng thất bại" |
| 103 | Điều phối bưu cục lấy hàng | Điều phối bưu cục lấy hàng | `READY_TO_PICK` | | |
| 104 | Lấy hàng điều phối bưu tá | Lấy hàng điều phối bưu tá | `READY_TO_PICK` | *xem dưới* | Bảng ghi "Y", đoạn Lưu ý không liệt kê |
| 107 | Đối tác yêu cầu hủy | Đối tác yêu cầu hủy qua API | `CANCELLED` | Y | |
| 200 | Lấy hàng thành công | Lấy hàng thành công | `PICKED` | | |
| 201 | Viettel Post hủy đơn hàng | Viettel Post hủy đơn hàng | `CANCELLED` | Y | |
| 202 | Sửa phiếu gửi | Sửa phiếu gửi | — | | Sửa thông tin, không phải di chuyển bưu gửi |
| 300 | Khai thác đi | Đóng tải | `IN_TRANSIT` | | |
| 400 | Khai thác đến | Bàn giao hoặc nhận bàn giao | `IN_TRANSIT` | | |
| 500 | Giao bưu tá đi phát | Phân công bưu tá đi giao hàng | `OUT_FOR_DELIVERY` | | |
| 501 | Thành công – Phát thành công | Thành công - Phát thành công | `DELIVERED` | Y | |
| 503 | Tiêu hủy – Theo yêu cầu khách hàng | Hủy - Theo yêu cầu khách hàng | — | Y | Tiêu hủy không trùng nghĩa `CANCELLED`/`RETURNED` |
| 504 | Thành công – Chuyển trả người gửi (Đơn hàng hoàn) | Thành công - Chuyển hoàn lại cho người gửi | `RETURNED` | Y | |
| 505 | Yêu cầu chuyển hoàn | Yêu cầu chuyển hoàn | — | | Dùng cho cả "khách từ chối" lẫn "người gửi yêu cầu hoàn" (lý do 43) |
| 506 | Phát thất bại | Phát thất bại - Khách hàng nghỉ, không có nhà/ Không nghe máy/ Hẹn giao lại | `DELIVERY_FAILED` | | |
| 507 | Khách hàng đến bưu cục nhận | Phát thất bại - Khách hàng đến bưu cục nhận | `DELIVERY_FAILED` | | |
| 508 | Phát tiếp | Đơn vị yêu cầu phát tiếp | — | | Là yêu cầu, chưa nói bưu tá đã đi phát |
| 509 | Chuyển tiếp bưu cục khác | Chuyển tiếp bưu cục khác | `IN_TRANSIT` | | |
| 515 | Duyệt hoàn | Bưu cục phát duyệt hoàn | `RETURNING` | | |
| 550 | Phát tiếp | Khách hàng yêu cầu phát tiếp | — | | Như 508 |

**15 mã có canonical**, **6 mã đã biết nhưng không có canonical rõ ràng** (102, 202, 503, 505, 508, 550).

Cột *Canonical* là **quyết định ánh xạ** của dự án dựa trên tên/mô tả chính thức; tài liệu VTP không tự công bố canonical của VIPORDER. Những mã mà việc gán sẽ là đoán thì để trống (`—`).

### Ba loại kết quả

`map_status()` trả `StatusMappingResult(provider_status, canonical_status, is_known, is_terminal, provider_status_name)`, kèm `requires_review = canonical_status is None`.

| Loại | `is_known` | `canonical_status` | Đổi trạng thái đơn? |
|---|---|---|---|
| Đã biết, có ánh xạ | `True` | giá trị canonical | có (do tầng cập nhật đơn quyết) |
| Đã biết, không có ánh xạ | `True` | `None` | **không** — ghi sự kiện, chờ xem xét |
| Không biết | `False` | `None` | **không** — ghi sự kiện, chờ xem xét |

### Chính sách mã không biết

1. Giữ nguyên `provider_status` gốc (chuỗi) và toàn bộ `DATA`.
2. **Không bao giờ** mặc định sang canonical nào — đặc biệt không sang `IN_TRANSIT` (bản scaffold cũ làm vậy; đã bỏ).
3. Đánh dấu `is_known=False`, `requires_review=True`, ghi log mức WARNING (không kèm PII) để dựng cảnh báo / hàng xem xét tay sau này.
4. Payload hợp lệ thì **ACK HTTP 200**: VTP thử lại tối đa 5 lần tới khi nhận 200, nên từ chối một mã mới chỉ tạo vòng thử lại vô ích và làm tắc hàng đợi tuần tự.

Mã không biết **không phải** payload hỏng. `ORDER_STATUS` sai kiểu (bool, số thực, số âm, chữ) mới là payload hỏng → HTTP 400.

### Trạng thái cuối

Đoạn *"Lưu ý"* ghi: trạng thái cuối là **101/107/201/501/503/504**, sau đó không phát sinh trạng thái mới; nếu vẫn có bản ghi mới thì đối tác ghi log và trả 200.

**Mâu thuẫn trong chính tài liệu:** bảng trạng thái đánh "Y" (cuối) cho **104**, nhưng đoạn Lưu ý không liệt kê 104, và 104 (điều phối bưu tá lấy hàng) đứng trước 200 (lấy hàng thành công) theo nghĩa nghiệp vụ. Mã nguồn theo đoạn Lưu ý: **104 không phải trạng thái cuối**. Cần hỏi VTP xác nhận.

`is_terminal` chỉ là cờ thông tin. Việc chặn sự kiện đến sau trạng thái cuối cần biết trạng thái hiện tại của đơn, thuộc tầng cập nhật đơn (ngoài phạm vi nhánh này).

### Điểm cần xác minh với Viettel Post

- 104 có phải trạng thái cuối không (mâu thuẫn bảng ↔ Lưu ý).
- Múi giờ của `ORDER_STATUSDATE` (tài liệu không nêu). Từ G05 (D-006): `occurred_at` để trống, giữ chữ gốc ở `occurred_at_raw`, luôn có `received_at`; bật `VTP_WEBHOOK_TIMEZONE` chỉ sau khi VTP xác nhận.
- Danh sách mã có đầy đủ không; mã ngoài bảng có thể xuất hiện ở thực tế (đã có chính sách mã không biết).
- Nghĩa nghiệp vụ của 505/508/550/503 để quyết có gán canonical hay cần thêm canonical mới (cần duyệt nghiệp vụ, đổi `ShipmentStatus` là việc của W-SHP-01).
