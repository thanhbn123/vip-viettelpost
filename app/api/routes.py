from fastapi import APIRouter, Depends

from app.api.auth import require_api_key
from app.api.finance import router as finance_router
from app.api.operations import router as operations_router
from app.api.shipping import router as shipping_router
from app.webhooks.routes import router as webhook_router

router = APIRouter()
protected = [Depends(require_api_key)]
router.include_router(
    shipping_router, prefix="/shipping", tags=["shipping"], dependencies=protected
)
router.include_router(
    operations_router, prefix="/shipping", tags=["operations"], dependencies=protected
)
router.include_router(
    finance_router, prefix="/shipping", tags=["finance"], dependencies=protected
)
router.include_router(webhook_router, prefix="/shipping/webhooks", tags=["webhooks"])
