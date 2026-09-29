from fastapi import APIRouter

from app.api.shipping import router as shipping_router
from app.webhooks.routes import router as webhook_router

router = APIRouter()
router.include_router(shipping_router, prefix="/shipping", tags=["shipping"])
router.include_router(webhook_router, prefix="/shipping/webhooks", tags=["webhooks"])
