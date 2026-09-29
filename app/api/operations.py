"""Operational shipment API (CR-SHP-001 G09)."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from app.api.dependencies import get_actor, get_operations
from app.api.errors import request_id_of
from app.api.schemas import (
    AuditView,
    ErrorBody,
    EventView,
    NoteBody,
    ShipmentPageView,
    ShipmentSummaryView,
    WebhookEventView,
)
from app.domain.models.common import ShippingProviderCode
from app.domain.models.shipment import ShipmentStatus
from app.repositories.shipping import Actor
from app.services.operations import MAX_PAGE, ShipmentOperations, ShipmentQuery

router = APIRouter()
Ops = Annotated[ShipmentOperations, Depends(get_operations)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
NOT_FOUND = {404: {"model": ErrorBody}}


@router.get("/shipments", response_model=ShipmentPageView)
def list_shipments(
    ops: Ops,
    status: Annotated[list[ShipmentStatus] | None, Query()] = None,
    provider: ShippingProviderCode | None = None,
    order_id: str | None = None,
    tracking_number: str | None = None,
    requires_review: bool | None = None,
    created_from: AwareDatetime | None = None,
    created_to: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ShipmentPageView:
    page = ops.search(
        ShipmentQuery(
            statuses=tuple(status or ()),
            provider=provider,
            order_id=order_id,
            tracking_number=tracking_number,
            requires_review=requires_review,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )
    )
    return ShipmentPageView(
        items=[
            ShipmentSummaryView(**{**asdict(i), "status": i.status.value}) for i in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/shipments/{shipment_id}/events", response_model=list[EventView], responses=NOT_FOUND)
def shipment_events(shipment_id: int, ops: Ops) -> list[EventView]:
    return [EventView(**asdict(e)) for e in ops.events(shipment_id)]


@router.get(
    "/shipments/{shipment_id}/webhook-events",
    response_model=list[WebhookEventView],
    responses=NOT_FOUND,
)
def shipment_webhook_events(shipment_id: int, ops: Ops) -> list[WebhookEventView]:
    return [WebhookEventView(**asdict(w)) for w in ops.webhook_events(shipment_id)]


@router.get("/shipments/{shipment_id}/audit", response_model=list[AuditView], responses=NOT_FOUND)
def shipment_audit(shipment_id: int, ops: Ops) -> list[AuditView]:
    return [AuditView(**asdict(a)) for a in ops.audit_trail(shipment_id)]


@router.post(
    "/shipments/{shipment_id}/notes",
    response_model=AuditView,
    status_code=201,
    responses=NOT_FOUND,
)
def add_note(
    shipment_id: int, body: NoteBody, request: Request, ops: Ops, actor: CurrentActor
) -> AuditView:
    return AuditView(
        **asdict(ops.add_note(shipment_id, body.text, actor=actor, request_id=request_id_of(request)))
    )

