# VIP Shipping Gateway

Gateway trung gian để tích hợp nhiều đơn vị vận chuyển vào hệ VIPORDER.  
Provider đầu tiên: **Viettel Post**.

## Mục tiêu V1

- Provider abstraction
- Viettel Post authentication/token
- Tạo / tra cứu / hủy vận đơn
- Tính cước / dịch vụ
- Webhook trạng thái
- Chuẩn hóa status nội bộ VIPORDER
- Idempotency / retry
- Audit log
- COD / đối soát ở mức nền tảng
- Không lưu secret trong Git
- Không deploy production trực tiếp

## Kiến trúc

Xem `docs/ARCHITECTURE.md` và `docs/architecture-overview.png`.

## Chạy local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Test

```bash
pytest -q
```

## Quy trình Git

Issue/CR → branch → code + test → PR → CI → verifier → develop → staging → main → production.

## Trạng thái

- Project scaffold: READY
- Viettel Post credentials: NOT INCLUDED
- Production deployment: NOT INCLUDED
