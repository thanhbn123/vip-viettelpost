# Viettel Post integration

## Luồng dự kiến

1. Authenticate/get token.
2. Query service capability.
3. Calculate fee.
4. Create shipment.
5. Save provider tracking number.
6. Receive webhook.
7. Persist raw event.
8. Deduplicate.
9. Map provider status.
10. Update shipment + audit.

## Chưa hard-code endpoint

Scaffold cố ý không điền endpoint/path cụ thể cho các API nghiệp vụ cho tới khi baseline và tài liệu Partner được xác minh trong phiên triển khai.
