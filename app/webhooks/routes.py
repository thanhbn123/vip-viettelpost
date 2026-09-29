from fastapi import APIRouter, Request
from app.providers.viettel_post.provider import ViettelPostProvider

router = APIRouter()

@router.post("/viettel-post")
async def viettel_post_webhook(request: Request):
    payload = await request.json()

    # TODO:
    # 1. verify webhook signature/shared secret if VTP supports it
    # 2. persist raw event
    # 3. enforce idempotency
    # 4. map provider status -> VIPORDER status
    # 5. append shipment event
    # 6. update shipment transactionally
    provider = ViettelPostProvider()
    return await provider.handle_webhook(payload)
