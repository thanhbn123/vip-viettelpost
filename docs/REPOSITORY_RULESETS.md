# Repository rulesets (CR-STG-002)

Nguồn chân lý: `.github/rulesets/*.json`. Áp bằng `python scripts/github/apply_rulesets.py` (idempotent; tạo nếu chưa có, cập nhật nếu lệch, **không** xoá ruleset không nằm trong thư mục). Mỗi thay đổi đi qua PR + CI + verifier như mã.

| Ruleset | Nhánh | Luật |
|---|---|---|
| `develop-baseline` | `develop` | cấm xoá; cấm force push; mọi thay đổi qua PR (0 lượt duyệt bắt buộc — một người bảo trì); bắt buộc check `lint`, `test`, `postgres`, `image`, `rehearsal` |
| `deploy-staging-baseline` | `deploy/staging` | cấm xoá; cấm force push; commit được đẩy phải có đủ các check trên |

Không có `bypass_actors`: kể cả admin cũng không đẩy thẳng lên `develop` được. Không đặt cho `main` trong CR này (main review là bước riêng của chủ dự án).

**Trạng thái áp dụng:** **đã áp** 2026-09-29 23:26:12 +07:00 bằng `apply_rulesets.py` chạy từ `develop` `5369d3b` (merge PR #30): `CREATE` ×2 → `deploy-staging-baseline` id `24193226`, `develop-baseline` id `24193228`, cả hai `active`. Chạy lại ngay sau đó in `SAME` ×2. Kiểm bằng GET `rules/branches/develop` (4 luật: `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks` gồm 5 check của app `15368`) và `rules/branches/deploy/staging` (3 luật). `main` vẫn 0 luật (không đụng tới). Trước khi áp: GET `/rulesets` = `[]`.

Giới hạn của bộ so lệch: chỉ xét trường khai báo trong JSON. `allowed_merge_methods` **không** được khai báo, nên nếu ai đó thu hẹp cách merge trên giao diện (vd chỉ còn squash) thì `apply_rulesets.py` **không** báo lệch.

Hệ quả vận hành:
- Rollback staging **không** đẩy lùi `deploy/staging` (bị cấm force push) — dùng phase `rollback` của hook, hoặc triển khai một commit `develop` mới hơn.
- Đổi tên job CI hoặc thêm `name:` cho job thì phải sửa JSON cùng PR, không thì mọi PR sẽ kẹt chờ check không tồn tại (`tests/unit/test_rulesets.py` kiểm cả 5 job và cấm `name:`).
- Ruleset `deploy/staging` **không** buộc commit nằm trên `develop` (check của PR chưa merge cũng đạt) — cổng thật là bước duyệt Environment `staging` và bước kiểm SHA trong workflow.
- CI hỏng diện rộng / đổi tên job làm kẹt merge: admin sửa ruleset (Settings → Rules, hoặc chạy lại `apply_rulesets.py` với JSON đã sửa) và ghi lý do vào `DECISIONS.md`.
- Drift chỉ xét trường khai báo trong JSON; trường GitHub tự thêm giá trị mặc định không tính là lệch. Sau khi áp, chạy lại `apply_rulesets.py` phải in `SAME`.
