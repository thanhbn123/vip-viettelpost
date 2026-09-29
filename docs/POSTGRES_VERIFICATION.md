# PostgreSQL verification (G13)

**Phạm vi đo:** PostgreSQL **16** (CI: service container `postgres:16`; cục bộ: cụm tạm 16.15), CSDL dùng một lần, schema `public` xoá/tạo lại trước mỗi test. **Không** đụng CSDL staging/production nào.

| Nội dung | Cách kiểm | Ở đâu |
|---|---|---|
| Migration upgrade / downgrade / upgrade lại | Alembic CLI trên PG + test migration chạy cả SQLite và PG | CI job `postgres`, `test_shipping_database_migrations.py` |
| ORM ↔ migration | `compare_metadata` (bảng, cột, kiểu, nullable, index, unique, FK) + đối chiếu tên CHECK; **không** so vị từ `WHERE` của index một phần → kiểm riêng bằng `pg_indexes` | `test_migration_matches_orm_metadata`, `test_check_constraints_match_orm`, `test_partial_unique_index_predicate_matches_the_model` |
| CRUD ORM | Toàn bộ test repository / API / webhook / finance chạy lại trên PG | CI job `postgres` |
| Kiểu cột gốc PG | `NUMERIC(18,2)`, `timestamp with time zone`, `jsonb` (information_schema) | `test_column_types_are_postgres_native` |
| Độ chính xác tiền | 0,01 · 9 999 999 999 999 999,99 · 123 456 789,10 trả về đúng `Decimal`; 10^16 bị CSDL từ chối (`DataError`) | `test_numeric_*` |
| JSON | JSONB giữ Unicode tiếng Việt và cấu trúc lồng; truy vấn `->>` được | `test_jsonb_round_trip_keeps_unicode_and_nesting` |
| Múi giờ | Ghi giờ +07, đọc ra UTC có múi giờ, cùng thời điểm | `test_timestamptz_is_stored_in_utc_and_returned_aware` |
| FK | `RESTRICT` chặn xoá hãng còn vận đơn | `test_foreign_keys_restrict` |
| CHECK | Trạng thái lạ, COD âm bị từ chối | `test_check_constraints_are_enforced` |
| Chống trùng webhook | UNIQUE `(provider_id, fingerprint)` từ chối bản ghi thứ hai ở mức CSDL; race đồng thời (8 luồng, retry `FAILED`, job replay) đã kiểm ở G05/G07 | `test_duplicate_webhook_fingerprint_is_refused_by_the_database`, `test_webhook_persistence.py`, `test_webhook_to_shipment.py` |
| Savepoint | Lỗi sau khi đã ghi dở + transaction PG bị huỷ → lùi về savepoint, commit ngoài vẫn thành công | `test_create_time_replay_savepoint_recovers_an_aborted_transaction` |
| Index danh sách | `shp_0004`: `(created_at, id)` cho `GET /shipments` | `test_shp_0004_created_index_up_and_down` |

**Ngoài phạm vi (chưa đo):** hiệu năng/khối lượng lớn, `CREATE INDEX CONCURRENTLY`, sao lưu/khôi phục, PG phiên bản khác 16, mức cô lập khác `READ COMMITTED` (ở `REPEATABLE READ` các lần giao trùng đồng thời sẽ lỗi tuần tự hoá → 5xx → hãng gửi lại: vẫn an toàn nhưng chưa có test), kết nối qua PgBouncer.
