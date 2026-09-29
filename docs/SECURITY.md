# Security rules

- Không commit `.env`.
- Không log password/token/Authorization header.
- Mask secret trong error reporting.
- Validate và authenticate webhook theo capability chính thức của provider.
- Store raw webhook event, nhưng loại bỏ/che thông tin nhạy cảm khi cần.
- Idempotency key/event fingerprint cho webhook.
- Least privilege cho shipping account.
- Rotate credentials theo quy trình vận hành.
