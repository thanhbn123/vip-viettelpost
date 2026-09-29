# API — VIP Shipping Gateway (trung lập với hãng)

Tiền tố: `/api/v1/shipping`. Mọi phản hồi mang header `X-Request-ID` (nhận từ bên gọi nếu ≤ 64 ký tự in được, không thì sinh mới); mã này được ghi vào audit.
**Chưa có xác thực bên gọi** (G12). Không mở ra Internet trước G12.

| Method | Path | Thân yêu cầu | Trả về |
|---|---|---|---|
| GET | `/health` | — | `{"status":"ok"}` |
| GET | `/providers` | — | `[ProviderView]`: `code`, `adapter_available`, `enabled` (có adapter **và** dòng `shipping_providers.enabled`) |
| POST | `/quote` | `QuoteBody` = `FeeRequest` + `provider` | `FeeQuote` |
| POST | `/shipments` | `CreateShipmentBody` = `CreateShipmentRequest` + `provider` | 201 `ShipmentView` |
| GET | `/shipments/{id}` | — | `ShipmentView` |
| GET | `/shipments/by-tracking/{tracking}` | query `provider` (tuỳ chọn) | `ShipmentView` |
| POST | `/shipments/{id}/cancel` | `{"reason": "..."}` (tuỳ chọn, ≤ 500) | `ShipmentView` |

`ShipmentView` = mô hình domain `Shipment` + `id`, `created_at`, `requires_review` (có sự kiện cần xem xét tay). Tiền là `{"amount": "<decimal>", "currency": "VND"}`; số thực (float) bị từ chối.
Trường riêng của hãng đi trong `provider_options` (VTP: xem `docs/VIETTEL_POST_INTEGRATION.md`).

## Luồng tạo vận đơn (D-023)

1. Giữ chỗ: ghi vận đơn `READY_TO_CREATE` (commit). Index unique một phần `shp_0003` chặn vận đơn **đang hoạt động** thứ hai cho cùng hãng + đơn → 409, **trước** khi gọi hãng (D-022).
2. Gọi hãng (ngoài transaction CSDL).
3. Ghi kết quả: thành công → `CREATED` + mã vận đơn + phí báo lúc tạo (`estimated_fee`); hãng từ chối / yêu cầu sai → `DRAFT` (giải phóng đơn để sửa và gửi lại); quá giờ / 5xx / phản hồi lạ → **giữ `READY_TO_CREATE`** + audit `PROVIDER_OUTCOME_UNKNOWN`: hãng có thể đã tạo đơn, nên đơn bị khoá tới khi người vận hành kiểm, không tạo mù lần hai.
4. Hãng tạo xong nhưng ghi CSDL hỏng → 500 `persistence_failed_after_provider_success` kèm mã vận đơn để đối soát; log mức ERROR.

Huỷ: chỉ khi có mã vận đơn và chưa ở trạng thái cuối (`DELIVERED`, `RETURNED`, `CANCELLED`) → 409 nếu không. Hãng huỷ lỗi → trạng thái giữ nguyên, audit `PROVIDER_CANCEL_FAILED`.

## Mã lỗi

Thân lỗi: `{"error": "<mã>", "detail": "<ngắn, an toàn>", "request_id": "..."}`. Không trả stack trace, SQL, token hay payload.

| HTTP | `error` | Khi nào |
|---|---|---|
| 404 | `shipment_not_found` | Không có vận đơn |
| 404 | `provider_not_supported` | Mã hãng hợp lệ nhưng chưa có adapter |
| 409 | `provider_disabled` | Hãng bị tắt trong `shipping_providers` |
| 409 | `duplicate_active_shipment` | Đơn đã có vận đơn đang hoạt động ở hãng này |
| 409 | `invalid_shipment_state` | Huỷ vận đơn đã kết thúc / chưa có mã; mã vận đơn trùng ở nhiều hãng |
| 422 | (FastAPI) | Thân yêu cầu sai kiểu / thiếu / thừa trường |
| 422 | `invalid_provider_request` | Yêu cầu không diễn đạt được cho hãng (thiếu `order_payment`, không phải VND...) |
| 422 | `mixed_currency` | Vận đơn dùng nhiều đơn vị tiền |
| 422 | `provider_rejected` | Hãng từ chối (thông điệp hãng đã qua lọc bí mật) |
| 502 | `provider_auth_failed` | Credential của gateway bị hãng từ chối (không lộ chi tiết) |
| 502 | `provider_bad_response` | Hãng trả phản hồi sai hợp đồng |
| 503 | `provider_unavailable` | Lỗi mạng / 5xx của hãng |
| 504 | `provider_timeout` | Hãng không trả lời kịp; **kết quả không rõ** |
| 500 | `persistence_failed_after_provider_success` | Xem bước 4 |
| 501 | `not_implemented` | Hãng không có tính năng (vd. tra cứu VTP) |
