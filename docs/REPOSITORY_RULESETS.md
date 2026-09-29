# Repository rulesets (CR-STG-002, CR-STG-003)

Nguồn chân lý: `.github/rulesets/*.json`. Áp bằng `python scripts/github/apply_rulesets.py` (idempotent; tạo nếu chưa có, cập nhật nếu lệch, **không** xoá ruleset không nằm trong thư mục). Mỗi thay đổi đi qua PR + CI + verifier như mã.

| Ruleset | Nhánh | Luật |
|---|---|---|
| `develop-baseline` | `develop` | cấm xoá; cấm force push; mọi thay đổi qua PR (0 lượt duyệt bắt buộc — một người bảo trì); bắt buộc check `lint`, `test`, `postgres`, `image`, `rehearsal` |
| `main-baseline` (CR-STG-003) | `main` | giống `develop-baseline`: cấm xoá; cấm force push; mọi thay đổi qua PR (0 lượt duyệt bắt buộc); bắt buộc 5 check trên |
| `deploy-staging-baseline` | `deploy/staging` | cấm xoá; cấm force push; commit được đẩy phải có đủ các check trên |

Không có `bypass_actors`: kể cả admin cũng không đẩy thẳng lên `develop` được. CR-STG-002 chưa đặt cho `main`; CR-STG-003 (issue #32) bổ sung `main-baseline`. Ruleset **không** thay bước review `develop → main` của chủ dự án: nó chỉ chặn đẩy thẳng, force push, xoá nhánh và merge khi CI chưa đạt. 0 lượt duyệt bắt buộc vì repo có một người bảo trì — GitHub không cho tác giả tự duyệt PR của mình, đặt 1 thì chính chủ dự án cũng không merge được.

**Trạng thái áp dụng:** **đã áp** 2026-09-29 23:26:12 +07:00 bằng `apply_rulesets.py` chạy từ `develop` `5369d3b` (merge PR #30): `CREATE` ×2 → `deploy-staging-baseline` id `24193226`, `develop-baseline` id `24193228`, cả hai `active`. Chạy lại ngay sau đó in `SAME` ×2. Kiểm bằng GET `rules/branches/develop` (4 luật: `deletion`, `non_fast_forward`, `pull_request`, `required_status_checks` gồm 5 check của app `15368`) và `rules/branches/deploy/staging` (3 luật). `main` lúc đó 0 luật (xem `main-baseline` bên dưới). Trước khi áp: GET `/rulesets` = `[]`.

**`main-baseline`:** **đã áp** 2026-09-29 23:41:30 +07:00 từ `develop` `c32934e` (merge PR #33): `CREATE` → id `24193826`, `active`; chạy lại in `SAME` ×3. GET `rules/branches/main` = 4 luật (`deletion`, `non_fast_forward`, `pull_request` 0 duyệt, `required_status_checks` 5 check app `15368`); `bypass_actors: []`, `current_user_can_bypass: never`. Phản chứng 23:41:53: `PATCH git/refs/heads/main` về chính SHA hiện tại `3b89b36` (không đổi gì nếu lọt) → HTTP 422 *Repository rule violations — Changes must be made through a pull request*. `main` giữ nguyên `3b89b36`.

Giới hạn của bộ so lệch: chỉ xét trường khai báo trong JSON. `allowed_merge_methods` **không** được khai báo, nên nếu ai đó thu hẹp cách merge trên giao diện (vd chỉ còn squash) thì `apply_rulesets.py` **không** báo lệch.

Hệ quả vận hành:
- Rollback staging **không** đẩy lùi `deploy/staging` (bị cấm force push) — dùng phase `rollback` của hook, hoặc triển khai một commit `develop` mới hơn.
- Đổi tên job CI hoặc thêm `name:` cho job thì phải sửa JSON cùng PR, không thì mọi PR sẽ kẹt chờ check không tồn tại (`tests/unit/test_rulesets.py` kiểm cả 5 job và cấm `name:`).
- Ruleset `deploy/staging` **không** buộc commit nằm trên `develop` (check của PR chưa merge cũng đạt) — cổng thật là bước duyệt Environment `staging` và bước kiểm SHA trong workflow.
- CI hỏng diện rộng / đổi tên job làm kẹt merge: admin sửa ruleset (Settings → Rules, hoặc chạy lại `apply_rulesets.py` với JSON đã sửa) và ghi lý do vào `DECISIONS.md`.
- Drift chỉ xét trường khai báo trong JSON; trường GitHub tự thêm giá trị mặc định không tính là lệch. Sau khi áp, chạy lại `apply_rulesets.py` phải in `SAME`.
