"""COD / fee / reconciliation API (CR-SHP-001 G10). Foundation only; see app/services/finance.py."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_actor, get_finance
from app.api.errors import request_id_of
from app.api.schemas import (
    CodCollectedBody,
    CodRemittedBody,
    ErrorBody,
    FeeBody,
    FeeLineView,
    FinanceViewModel,
    ReconciliationBody,
    ReconciliationView,
    ResolveBody,
)
from app.repositories.shipping import Actor
from app.services.finance import FinanceView, ShipmentFinance

router = APIRouter()
Finance = Annotated[ShipmentFinance, Depends(get_finance)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
ERRORS = {code: {"model": ErrorBody} for code in (404, 409, 422)}


def _view(v: FinanceView) -> FinanceViewModel:
    data = asdict(v)
    data["fees"] = [FeeLineView(**f) for f in data["fees"]]
    data["reconciliations"] = [ReconciliationView(**r) for r in data["reconciliations"]]
    return FinanceViewModel(**data)


@router.get("/shipments/{shipment_id}/finance", response_model=FinanceViewModel, responses=ERRORS)
def finance(shipment_id: int, fin: Finance) -> FinanceViewModel:
    return _view(fin.view(shipment_id))


@router.post(
    "/shipments/{shipment_id}/cod/collected", response_model=FinanceViewModel, responses=ERRORS
)
def cod_collected(
    shipment_id: int, body: CodCollectedBody, request: Request, fin: Finance, actor: CurrentActor
) -> FinanceViewModel:
    return _view(
        fin.record_cod_collected(
            shipment_id,
            body.amount.amount,
            body.amount.currency,
            actor=actor,
            collected_at=body.collected_at,
            request_id=request_id_of(request),
        )
    )


@router.post(
    "/shipments/{shipment_id}/cod/remitted", response_model=FinanceViewModel, responses=ERRORS
)
def cod_remitted(
    shipment_id: int, body: CodRemittedBody, request: Request, fin: Finance, actor: CurrentActor
) -> FinanceViewModel:
    return _view(
        fin.record_cod_remitted(
            shipment_id,
            body.amount.amount,
            body.amount.currency,
            body.reference,
            actor=actor,
            remitted_at=body.remitted_at,
            request_id=request_id_of(request),
        )
    )


@router.post(
    "/shipments/{shipment_id}/fees",
    response_model=FinanceViewModel,
    status_code=201,
    responses=ERRORS,
)
def add_fee(
    shipment_id: int, body: FeeBody, request: Request, fin: Finance, actor: CurrentActor
) -> FinanceViewModel:
    return _view(
        fin.add_fee(
            shipment_id,
            fee_type=body.fee_type,
            source=body.source,
            amount=body.amount,
            currency=body.currency,
            note=body.note,
            provider_reference=body.provider_reference,
            actor=actor,
            request_id=request_id_of(request),
        )
    )


@router.post(
    "/shipments/{shipment_id}/reconciliations",
    response_model=FinanceViewModel,
    status_code=201,
    responses=ERRORS,
)
def reconcile(
    shipment_id: int, body: ReconciliationBody, request: Request, fin: Finance, actor: CurrentActor
) -> FinanceViewModel:
    return _view(
        fin.reconcile(
            shipment_id,
            kind=body.kind,
            actual_amount=body.actual_amount.amount,
            currency=body.actual_amount.currency,
            statement_reference=body.statement_reference,
            actor=actor,
            request_id=request_id_of(request),
        )
    )


@router.post(
    "/reconciliations/{reconciliation_id}/resolve",
    response_model=FinanceViewModel,
    responses=ERRORS,
)
def resolve(
    reconciliation_id: int, body: ResolveBody, request: Request, fin: Finance, actor: CurrentActor
) -> FinanceViewModel:
    return _view(
        fin.resolve(reconciliation_id, body.note, actor=actor, request_id=request_id_of(request))
    )
