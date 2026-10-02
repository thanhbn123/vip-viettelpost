# Viettel Post DEVELOPMENT E2E (G08)

Trạng thái (2026-10-02): **G08 BLOCKED_EXTERNAL_CREDENTIAL** — PASS chỉ-đọc ngày 01/10 **đã rút lại** (CR-STG-007): với token tĩnh, bước authenticate không gọi mạng và getPriceAll/getPrice của partnerdev **không kiểm token** (token giả cũng PASS); `createOrder` với `VTP_TOKEN` hiện tại trả lỗi xác thực (run 36900122982: tạo đơn **đã thử và FAIL**, không có đơn nào được tạo; huỷ bỏ qua). Phần "Lịch sử" dưới đây ghi trạng thái cũ. Luật G08 nay đòi Login+ownerconnect PASS **hoặc** tạo + huỷ đơn thử PASS. Lịch sử: **G08 PASS — chỉ đọc** (bước 1–3: authenticate, services, fee) — run 36757608002 attempt 4, SHA `c6ee0d6`, partnerdev, xác thực bằng `VTP_TOKEN` (token tĩnh: bước authenticate không gọi mạng, token được kiểm gián tiếp qua getPriceAll/getPrice). **Chưa chạy:** tạo/huỷ đơn (cần D-BIZ-001 + cờ cho phép), callback webhook thật, đăng nhập Login/ownerconnect bằng tài khoản Partner dev. Lịch sử: **`BLOCKED_EXTERNAL_CREDENTIAL`** — chưa có credential dev (đo 2026-09-29). Không chạy khi chưa có. Không bao giờ gọi production.

## Tên biến (từ code)
| Biến | Bắt buộc | Ghi chú |
|---|---|---|
| `VTP_BASE_URL` | có | Phải đúng `https://partnerdev.viettelpost.vn`; script **từ chối** mọi giá trị khác (thoát 2, không gửi yêu cầu nào) |
| `VTP_TOKEN` **hoặc** `VTP_USERNAME` + `VTP_PASSWORD` | có | Thiếu → `BLOCKED_EXTERNAL_CREDENTIAL` (thoát 3) |
| `VTP_E2E_SCENARIO` | có | Đường dẫn JSON kịch bản (workflow tạo từ var `VTP_E2E_SCENARIO_JSON`); mẫu `scripts/vtp_dev_e2e.scenario.example.json` |
| `VTP_E2E_ALLOW_CREATE` | không | `yes` + cờ `--create` mới tạo đơn thử |
| `VTP_TIMEOUT_SECONDS` | không | Mặc định 20 s |

## Luồng xác thực (theo tài liệu Partner, đã xác minh ở PR #2)
- Có `VTP_TOKEN` → dùng nguyên, không gọi đăng nhập.
- Không có → `POST /v2/user/Login` (USERNAME/PASSWORD) → `POST /v2/user/ownerconnect` (header `Token`) → token dài hạn trong bộ nhớ tiến trình.
- Token chỉ nằm trong adapter; không in, không ghi file, không vào lỗi (`redact`).

## Trình tự an toàn (`scripts/vtp_dev_e2e.py`)
| # | Bước | Endpoint | Tạo trạng thái ở VTP? | Mặc định |
|---|---|---|---|---|
| 1 | authenticate | Login + ownerconnect (hoặc token tĩnh) | Không (chỉ cấp token) | chạy |
| 2 | get services | `POST /v2/order/getPriceAll` | Không | chạy |
| 3 | calculate fee | `POST /v2/order/getPrice` | Không | chạy (dịch vụ từ kịch bản hoặc dịch vụ đầu tiên của bước 2). Bước 2 trả rỗng → FAIL; bước 3 bị bỏ qua → run **không** đạt |
| 4 | create shipment | `POST /v2/order/createOrder` | **Có — một đơn thử ở VTP dev** | **không** chạy trừ khi `--create` **và** `VTP_E2E_ALLOW_CREATE=yes` **và** bước 1–3 đều PASS; cần `order_payment` trong kịch bản (D-BIZ-001) |
| 5 | cancel shipment | `POST /v2/order/UpdateOrder` `TYPE=4` | Đưa đơn thử về huỷ | tự chạy ngay sau bước 4 |
| 6 | webhook | VTP dev gọi `https://<staging>/api/v1/shipping/webhooks/viettel-post` | — | chỉ khi staging có URL công khai và đã đăng ký với VTP (G15) |

**Huỷ được / không huỷ được:** tài liệu VTP chỉ cho huỷ (`TYPE=4`) khi `ORDER_STATUS < 200` (chưa lấy hàng) — huỷ ngay sau tạo là trong điều kiện này. Nếu bước 5 lỗi, đơn thử **còn tồn tại ở VTP dev**: mã vận đơn nằm trong bằng chứng để huỷ tay.

## Bằng chứng mong đợi (không bí mật, không dữ liệu cá nhân)
File JSON (`--evidence`, workflow đưa vào job summary): URL gốc, giờ bắt đầu, mỗi bước `PASS/FAIL/SKIPPED/NOT_SAFE`, thời lượng ms, và: `authenticated`, số dịch vụ + mã dịch vụ, tổng cước + đơn vị, mã đơn/mã vận đơn/trạng thái, kết quả huỷ; lỗi chỉ ghi **tên lớp lỗi**. Sau khi chạy: so từng kết quả với tài liệu Partner (dạng phản hồi `getPriceAll` là mảng trần — R-007) và ghi vào `MASTER_STATUS.md`.

## Giới hạn thời gian / thử lại
Mỗi yêu cầu ≤ `VTP_TIMEOUT_SECONDS` (20 s). Script **không** thử lại bước nào (kể cả chỉ-đọc) để bằng chứng phản ánh đúng một lần gọi; tạo/huỷ không bao giờ tự thử lại (D-023, D-031). Lỗi token → adapter làm mới **một lần** nếu dùng username/password.

## Chạy
- Qua workflow `staging.yml`: đẩy `deploy/staging` tới một commit của `develop` với var `RUN_VTP_DEV_E2E=true` (đặt ở Environment `staging`; job `preflight` — chạy trong Environment — quyết định `run_e2e`, vì `if:` cấp job không đọc được biến của Environment: CR-STG-006, run 36755351460 đã bị bỏ qua vì lỗi này) (thêm `VTP_E2E_CREATE_TEST_ORDER=yes` + `VTP_E2E_ALLOW_CREATE=yes` nếu đã duyệt tạo đơn thử); hoặc *Run workflow* khi file đã có trên `main` (chọn *Use workflow from: `develop`*). Credential lấy từ Environment `staging`, job cần người duyệt.
- Tại máy tin cậy, **từ thư mục gốc repo**: nạp biến bằng `read` không vang (không để trong lịch sử shell), rồi `python -m scripts.vtp_dev_e2e [--create]` (chạy dạng module để `app` import được).

## Test
`tests/unit/test_vtp_dev_e2e_script.py` (HTTP giả lập; kèm test chạy **đúng lệnh** `python -m scripts.vtp_dev_e2e` bằng subprocess): từ chối URL production mà không gửi gì; thiếu credential → BLOCKED; mặc định không tạo đơn; tạo cần cả cờ và biến cho phép; tạo xong huỷ ngay; bước lỗi được ghi, không làm dừng báo cáo; token và SĐT không xuất hiện trong đầu ra.
