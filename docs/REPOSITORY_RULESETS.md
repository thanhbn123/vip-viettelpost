# Repository rulesets (CR-STG-002)

Nguồn chân lý: `.github/rulesets/*.json`. Áp bằng `python scripts/github/apply_rulesets.py` (idempotent; tạo nếu chưa có, cập nhật nếu lệch, **không** xoá ruleset không nằm trong thư mục). Mỗi thay đổi đi qua PR + CI + verifier như mã.

| Ruleset | Nhánh | Luật |
|---|---|---|
| `develop-baseline` | `develop` | cấm xoá; cấm force push; mọi thay đổi qua PR (0 lượt duyệt bắt buộc — một người bảo trì); bắt buộc check `lint`, `test`, `postgres`, `image`, `rehearsal` |
| `deploy-staging-baseline` | `deploy/staging` | cấm xoá; cấm force push; commit được đẩy phải có đủ các check trên |

Không có `bypass_actors`: kể cả admin cũng không đẩy thẳng lên `develop` được. Không đặt cho `main` trong CR này (main review là bước riêng của chủ dự án).

Hệ quả vận hành:
- Rollback staging **không** đẩy lùi `deploy/staging` (bị cấm force push) — dùng phase `rollback` của hook, hoặc triển khai một commit `develop` mới hơn.
- Đổi tên job CI thì phải sửa JSON cùng PR, không thì mọi PR sẽ kẹt chờ check không tồn tại (`tests/unit/test_rulesets.py` bắt lệch tên cho 4 job gốc).
