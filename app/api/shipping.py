from fastapi import APIRouter, HTTPException
from app.core.container import get_shipping_service

router = APIRouter()

@router.get("/providers")
def providers():
    return [{"code": "VIETTEL_POST", "enabled": False, "status": "scaffold"}]

@router.post("/shipments")
async def create_shipment(payload: dict):
    service = get_shipping_service()
    try:
        result = await service.create_shipment("VIETTEL_POST", payload)
        return result
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
