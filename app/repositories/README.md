# Repository layer

`shipping.py` — `ShippingRepository` (sync, SQLAlchemy 2.0):

- providers / accounts (`secret_reference` chỉ là con trỏ, không phải bí mật)
- create shipment (kèm kiện, dòng COD nếu COD > 0, audit `SHIPMENT_CREATED`)
- get shipment by id / by (provider, tracking)
- append shipment event (chỉ ghi thêm, chống trùng theo `provider_event_id`)
- record webhook event + idempotency check (fingerprint / event_id)
- write audit log

Repository chỉ `flush`, không `commit`: bên gọi giữ transaction.
Trả bản ghi ORM; ánh xạ sang domain model là việc của service (xem
`docs/DATABASE_SCHEMA.md` mục 12).

`redaction.py` — header webhook qua danh sách trắng; payload/audit che khoá có dạng bí mật.
