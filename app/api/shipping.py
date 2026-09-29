from fastapi import APIRouter, HTTPException

from app.core.container import get_shipping_service
from app.providers.base.dto import CreateShipmentRequest, CreateShipmentResult
from app.providers.viettel_post.provider import ViettelPostRequestError
from app.repositories.mappers import MixedCurrencyError

router = APIRouter()


@router.get("/providers")
def providers():
    return [{"code": "VIETTEL_POST", "enabled": False, "status": "scaffold"}]


@router.post("/shipments", response_model=CreateShipmentResult)
async def create_shipment(payload: CreateShipmentRequest) -> CreateShipmentResult:
    # Interim typed route (G05). The provider-neutral application API with persistence,
    # error mapping and audit is G06.
    service = get_shipping_service()
    try:
        return await service.create_shipment("VIETTEL_POST", payload)
    except (ViettelPostRequestError, MixedCurrencyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
