# Database

Không tự CREATE/ALTER schema ở runtime. Schema chỉ do Alembic tạo (`migrations/`).

- `base.py`: `Base` + naming convention (quy ước đặt tên ràng buộc).
- `models.py`: 10 bảng shipping (bản ghi DB, không phải domain model).
- `types.py`: `MoneyType` (NUMERIC(18,2) / SQLite BIGINT x100, cấm float), `UTCDateTime`, JSON/JSONB.
- `session.py`: `make_engine` (SQLite: bật foreign_keys, sửa SAVEPOINT) và `make_session_factory`.

Mọi thay đổi DB phải qua migration có:
- upgrade
- downgrade/rollback plan
- review
- staging verification

Chi tiết: `docs/DATABASE_SCHEMA.md`.
