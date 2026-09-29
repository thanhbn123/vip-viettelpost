"""COD / fee / reconciliation foundation (CR-SHP-001 G10).

Records numbers faithfully and derives statuses MECHANICALLY; it is not an accounting
engine. Who owns COD money, when it counts as settled and who may adjust fees are
business rules still to be decided (RISK R-011) - nothing here encodes them.

* Amounts are exact ``Decimal`` with at most 2 decimals, in the shipment's currency.
* COD status: collected == expected -> COLLECTED, otherwise PARTIAL; remitted == collected
  -> REMITTED. A shipment without COD has no ``shipment_cod`` row and rejects COD calls.
* Fees: PROVIDER_ACTUAL and ADJUSTMENT lines; ``shipments.actual_fee`` = their sum and must
  stay >= 0. ADJUSTMENT lines may be negative and require a note.
* Reconciliation: one row per comparison against a provider statement; difference =
  actual - expected; MATCHED when 0, else MISMATCH; RESOLVED only by an explicit call.
* Every change writes an audit row with before/after.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Shipment as ShipmentRecord
from app.db.models import ShipmentCod, ShipmentFee, ShipmentReconciliation
from app.db.types import to_money
from app.repositories.shipping import Actor, AuditAction, ShippingRepository
from app.services.shipping_app import (
    ApplicationError,
    InvalidShipmentStateError,
    ShipmentNotFoundError,
)

FeeSource = Literal["PROVIDER_ACTUAL", "ADJUSTMENT"]
ReconciliationKind = Literal["COD", "FEE"]


class FinanceError(ApplicationError):
    code = "invalid_finance_operation"


class ReconciliationNotFoundError(ApplicationError, LookupError):
    code = "reconciliation_not_found"


@dataclass(frozen=True)
class FeeLine:
    id: int
    fee_type: str
    source: str
    amount: Decimal
    currency: str
    note: str | None
    provider_reference: str | None
    created_at: datetime


@dataclass(frozen=True)
class ReconciliationLine:
    id: int
    kind: str
    statement_reference: str | None
    expected_amount: Decimal
    actual_amount: Decimal
    difference_amount: Decimal
    currency: str
    status: str
    note: str | None
    reconciled_at: datetime | None


@dataclass(frozen=True)
class FinanceView:
    shipment_id: int
    currency: str
    cod_expected: Decimal | None
    cod_collected: Decimal | None
    cod_remitted: Decimal | None
    cod_status: str | None
    cod_collected_at: datetime | None
    cod_remitted_at: datetime | None
    remittance_reference: str | None
    estimated_fee: Decimal | None
    actual_fee: Decimal | None
    fees: list[FeeLine]
    reconciliations: list[ReconciliationLine]


def _now() -> datetime:
    return datetime.now(UTC)


class ShipmentFinance:
    def __init__(self, sessions: sessionmaker[Session], *, clock=_now) -> None:
        self._sessions = sessions
        self._clock = clock

    # -- helpers ----------------------------------------------------------------------

    @staticmethod
    def _shipment(session: Session, shipment_id: int, *, lock: bool = False) -> ShipmentRecord:
        stmt = select(ShipmentRecord).where(ShipmentRecord.id == shipment_id)
        if lock:
            stmt = stmt.with_for_update()
        record = session.scalar(stmt)
        if record is None:
            raise ShipmentNotFoundError(f"shipment {shipment_id} not found")
        return record

    @staticmethod
    def _amount(value: Decimal, currency: str, record: ShipmentRecord, *, signed=False) -> Decimal:
        if currency != record.currency:
            raise FinanceError(
                f"amount currency {currency} differs from shipment {record.currency}"
            )
        try:
            amount = to_money(value)
        except (TypeError, ValueError) as exc:
            raise FinanceError(str(exc)) from exc
        if amount < 0 and not signed:
            raise FinanceError("amount must not be negative")
        return amount

    @staticmethod
    def _cod(session: Session, shipment_id: int) -> ShipmentCod | None:
        return session.scalar(select(ShipmentCod).where(ShipmentCod.shipment_id == shipment_id))

    def _audit(
        self, session, shipment_id, action, actor, before, after, reason=None, request_id=None
    ):
        ShippingRepository(session).write_audit_log(
            entity_type="shipment",
            entity_id=str(shipment_id),
            action=action,
            actor=actor,
            before=before,
            after=after,
            reason=reason,
            request_id=request_id,
        )

    # -- read -------------------------------------------------------------------------

    def view(self, shipment_id: int) -> FinanceView:
        with self._sessions() as session:
            record = self._shipment(session, shipment_id)
            cod = self._cod(session, shipment_id)
            fees = session.scalars(
                select(ShipmentFee)
                .where(ShipmentFee.shipment_id == shipment_id)
                .order_by(ShipmentFee.id)
            ).all()
            recs = session.scalars(
                select(ShipmentReconciliation)
                .where(ShipmentReconciliation.shipment_id == shipment_id)
                .order_by(ShipmentReconciliation.id)
            ).all()
            return FinanceView(
                shipment_id=shipment_id,
                currency=record.currency,
                cod_expected=cod.expected_amount if cod else None,
                cod_collected=cod.collected_amount if cod else None,
                cod_remitted=cod.remitted_amount if cod else None,
                cod_status=cod.status if cod else None,
                cod_collected_at=cod.collected_at if cod else None,
                cod_remitted_at=cod.remitted_at if cod else None,
                remittance_reference=cod.remittance_reference if cod else None,
                estimated_fee=record.estimated_fee,
                actual_fee=record.actual_fee,
                fees=[
                    FeeLine(
                        f.id,
                        f.fee_type,
                        f.source,
                        f.amount,
                        f.currency,
                        f.note,
                        f.provider_reference,
                        f.created_at,
                    )
                    for f in fees
                ],
                reconciliations=[
                    ReconciliationLine(
                        r.id,
                        r.kind,
                        r.statement_reference,
                        r.expected_amount,
                        r.actual_amount,
                        r.difference_amount,
                        r.currency,
                        r.status,
                        r.note,
                        r.reconciled_at,
                    )
                    for r in recs
                ],
            )

    # -- COD ----------------------------------------------------------------------------

    def record_cod_collected(
        self,
        shipment_id,
        amount: Decimal,
        currency: str,
        *,
        actor: Actor,
        collected_at: datetime | None = None,
        request_id: str | None = None,
    ) -> FinanceView:
        with self._sessions() as session, session.begin():
            record = self._shipment(session, shipment_id, lock=True)
            cod = self._cod(session, shipment_id)
            if cod is None:
                raise FinanceError(f"shipment {shipment_id} has no COD")
            if cod.status in ("REMITTED", "CANCELLED"):
                raise InvalidShipmentStateError(f"COD already {cod.status}")
            value = self._amount(amount, currency, record)
            before = {"collected_amount": str(cod.collected_amount), "status": cod.status}
            cod.collected_amount = value
            cod.collected_at = collected_at or self._clock()
            cod.status = "COLLECTED" if value == cod.expected_amount else "PARTIAL"
            session.flush()
            self._audit(
                session,
                shipment_id,
                AuditAction.COD_CHANGED,
                actor,
                before,
                {"collected_amount": str(value), "status": cod.status},
                request_id=request_id,
            )
        return self.view(shipment_id)

    def record_cod_remitted(
        self,
        shipment_id,
        amount: Decimal,
        currency: str,
        reference: str,
        *,
        actor: Actor,
        remitted_at: datetime | None = None,
        request_id: str | None = None,
    ) -> FinanceView:
        with self._sessions() as session, session.begin():
            record = self._shipment(session, shipment_id, lock=True)
            cod = self._cod(session, shipment_id)
            if cod is None:
                raise FinanceError(f"shipment {shipment_id} has no COD")
            if cod.collected_amount is None:
                raise InvalidShipmentStateError("COD not collected yet")
            value = self._amount(amount, currency, record)
            before = {"remitted_amount": str(cod.remitted_amount), "status": cod.status}
            cod.remitted_amount = value
            cod.remitted_at = remitted_at or self._clock()
            cod.remittance_reference = reference
            if value == cod.collected_amount:
                cod.status = "REMITTED"
            session.flush()
            self._audit(
                session,
                shipment_id,
                AuditAction.COD_CHANGED,
                actor,
                before,
                {
                    "remitted_amount": str(value),
                    "status": cod.status,
                    "remittance_reference": reference,
                },
                request_id=request_id,
            )
        return self.view(shipment_id)

    # -- fees ---------------------------------------------------------------------------

    def add_fee(
        self,
        shipment_id,
        *,
        fee_type: str,
        source: FeeSource,
        amount: Decimal,
        currency: str,
        actor: Actor,
        note: str | None = None,
        provider_reference: str | None = None,
        request_id: str | None = None,
    ) -> FinanceView:
        if source == "ADJUSTMENT" and not note:
            raise FinanceError("an adjustment requires a note")
        with self._sessions() as session, session.begin():
            record = self._shipment(session, shipment_id, lock=True)
            value = self._amount(amount, currency, record, signed=source == "ADJUSTMENT")
            lines = session.scalars(
                select(ShipmentFee.amount).where(
                    ShipmentFee.shipment_id == shipment_id,
                    ShipmentFee.source.in_(("PROVIDER_ACTUAL", "ADJUSTMENT")),
                )
            ).all()
            new_total = sum(lines, Decimal(0)) + value
            if new_total < 0:
                raise FinanceError("the actual fee would become negative")
            session.add(
                ShipmentFee(
                    shipment_id=shipment_id,
                    fee_type=fee_type,
                    source=source,
                    amount=value,
                    currency=record.currency,
                    note=note,
                    provider_reference=provider_reference,
                    created_by=actor.id,
                )
            )
            before = {"actual_fee": None if record.actual_fee is None else str(record.actual_fee)}
            record.actual_fee = to_money(new_total)
            session.flush()
            action = (
                AuditAction.RECONCILIATION_ADJUSTED if source == "ADJUSTMENT" else "FEE_RECORDED"
            )
            self._audit(
                session,
                shipment_id,
                action,
                actor,
                before,
                {
                    "actual_fee": str(record.actual_fee),
                    "line": str(value),
                    "fee_type": fee_type,
                    "source": source,
                },
                reason=note,
                request_id=request_id,
            )
        return self.view(shipment_id)

    # -- reconciliation -----------------------------------------------------------------

    def reconcile(
        self,
        shipment_id,
        *,
        kind: ReconciliationKind,
        actual_amount: Decimal,
        currency: str,
        statement_reference: str | None,
        actor: Actor,
        request_id: str | None = None,
    ) -> FinanceView:
        with self._sessions() as session, session.begin():
            record = self._shipment(session, shipment_id, lock=True)
            actual = self._amount(actual_amount, currency, record)
            if kind == "COD":
                cod = self._cod(session, shipment_id)
                expected = cod.expected_amount if cod else Decimal("0.00")
            else:
                if record.estimated_fee is None:
                    raise FinanceError("no expected fee to reconcile against")
                expected = record.estimated_fee
            difference = to_money(actual - expected)
            status = "MATCHED" if difference == 0 else "MISMATCH"
            session.add(
                ShipmentReconciliation(
                    shipment_id=shipment_id,
                    provider_id=record.provider_id,
                    kind=kind,
                    statement_reference=statement_reference,
                    expected_amount=expected,
                    actual_amount=actual,
                    difference_amount=difference,
                    currency=record.currency,
                    status=status,
                    reconciled_at=self._clock(),
                    created_by=actor.id,
                )
            )
            session.flush()
            self._audit(
                session,
                shipment_id,
                "RECONCILIATION_RECORDED",
                actor,
                None,
                {
                    "kind": kind,
                    "expected": str(expected),
                    "actual": str(actual),
                    "difference": str(difference),
                    "status": status,
                    "statement_reference": statement_reference,
                },
                request_id=request_id,
            )
        return self.view(shipment_id)

    def resolve(
        self, reconciliation_id: int, note: str, *, actor: Actor, request_id: str | None = None
    ) -> FinanceView:
        with self._sessions() as session, session.begin():
            rec = session.get(ShipmentReconciliation, reconciliation_id, with_for_update=True)
            if rec is None:
                raise ReconciliationNotFoundError(f"reconciliation {reconciliation_id} not found")
            if rec.status != "MISMATCH":
                raise InvalidShipmentStateError(f"reconciliation is {rec.status}, not MISMATCH")
            before = {"status": rec.status}
            rec.status = "RESOLVED"
            rec.note = note
            session.flush()
            self._audit(
                session,
                rec.shipment_id,
                AuditAction.RECONCILIATION_ADJUSTED,
                actor,
                before,
                {"status": "RESOLVED", "reconciliation_id": rec.id},
                reason=note,
                request_id=request_id,
            )
            shipment_id = rec.shipment_id
        return self.view(shipment_id)
