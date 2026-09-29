# Migrations

Alembic, cấu hình trọn trong thư mục này. Chạy từ gốc repo:

```bash
alembic -c migrations/alembic.ini heads
alembic -c migrations/alembic.ini -x db_url=sqlite:///./local.db upgrade head
alembic -c migrations/alembic.ini -x db_url=sqlite:///./local.db downgrade base
```

Không có URL mặc định: phải truyền `-x db_url=...` hoặc đặt `DATABASE_URL`.

Revision:
- `shp_0001_shipping_gateway` — 10 bảng: shipping_providers, shipping_accounts,
  shipments, shipment_packages, shipment_events, shipment_fees, shipment_cod,
  shipment_reconciliation, shipping_webhook_events, shipping_audit_logs.

Revision không import code ứng dụng. Chi tiết: `docs/DATABASE_SCHEMA.md`.
