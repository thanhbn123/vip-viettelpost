from fastapi import APIRouter

from app.api.finance import router as finance_router
from app.api.operations import router as operations_router
from app.api.shipping import router as shipping_router
from app.webhooks.routes import router as webhook_router

router = APIRouter()
router.include_router(shipping_router, prefix="/shipping", tags=["shipping"])
router.include_router(operations_router, prefix="/shipping", tags=["operations"])
router.include_router(finance_router, prefix="/shipping", tags=["finance"])
router.include_router(webhook_router, prefix="/shipping/webhooks", tags=["webhooks"])
