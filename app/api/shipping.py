"""Provider-neutral shipping API (CR-SHP-001 G06)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_actor, get_application
from app.api.errors import request_id_of
from app.api.schemas import (
    CancelShipmentBody,
    CreateShipmentBody,
    ErrorBody,
    ProviderView,
    QuoteBody,
    ShipmentView,
)
from app.domain.models.common import ShippingProviderCode
from app.providers.base.dto import FeeQuote, FeeRequest
from app.repositories.shipping import Actor
from app.services.shipping_app import ShippingApplication, StoredShipment

router = APIRouter()
App = Annotated[ShippingApplication, Depends(get_application)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
ERRORS = {code: {"model": ErrorBody} for code in (404, 409, 422, 500, 501, 502, 503, 504)}


def _view(stored: StoredShipment) -> ShipmentView:
    return ShipmentView(
        **stored.shipment.model_dump(),
        id=stored.id,
        created_at=stored.created_at,
        requires_review=stored.requires_review,
    )


@router.get("/providers", response_model=list[ProviderView])
def list_providers(app: App) -> list[ProviderView]:
    return [
        ProviderView(code=p.code, adapter_available=p.adapter_available, enabled=p.enabled)
        for p in app.list_providers()
    ]


@router.post("/quote", response_model=FeeQuote, responses=ERRORS)
async def quote(body: QuoteBody, app: App) -> FeeQuote:
    request = FeeRequest.model_validate(body.model_dump(exclude={"provider"}))
    return await app.quote(body.provider, request)


@router.post("/shipments", response_model=ShipmentView, status_code=201, responses=ERRORS)
async def create_shipment(
    body: CreateShipmentBody, request: Request, app: App, actor: CurrentActor
) -> ShipmentView:
    stored = await app.create_shipment(
        body.provider, body.to_request(), actor=actor, request_id=request_id_of(request)
    )
    return _view(stored)


@router.get(
    "/shipments/by-tracking/{tracking_number}", response_model=ShipmentView, responses=ERRORS
)
def get_by_tracking(
    tracking_number: str, app: App, provider: ShippingProviderCode | None = None
) -> ShipmentView:
    return _view(app.get_by_tracking(tracking_number, provider))


@router.get("/shipments/{shipment_id}", response_model=ShipmentView, responses=ERRORS)
def get_shipment(shipment_id: int, app: App) -> ShipmentView:
    return _view(app.get_shipment(shipment_id))


@router.post("/shipments/{shipment_id}/cancel", response_model=ShipmentView, responses=ERRORS)
async def cancel_shipment(
    shipment_id: int,
    request: Request,
    app: App,
    actor: CurrentActor,
    body: CancelShipmentBody | None = None,
) -> ShipmentView:
    stored = await app.cancel_shipment(
        shipment_id,
        actor=actor,
        reason=body.reason if body else None,
        request_id=request_id_of(request),
    )
    return _view(stored)
