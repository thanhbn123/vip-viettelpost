"""Explicit mapping between domain models (``app.domain``) and persistence records
(``app.db.models`` / repository inputs). Domain models never inherit SQLAlchemy.

Decisions (docs/DECISIONS.md, docs/INTEGRATION_NOTES.md):

* provider: ``ShippingProviderCode`` <-> ``shipping_providers.code`` (row id looked up).
* money: domain ``Money(amount, currency)`` <-> exact ``Decimal`` column + one ``currency``
  column per shipment. A shipment whose amounts use different currencies is rejected.
* COD: domain ``None`` (no collection) <-> DB ``0`` (column is NOT NULL DEFAULT 0).
  A DB ``0`` is read back as ``None``.
* fee: domain ``Shipment.fee`` is the provider's actual fee when known, else the estimate.
* events: domain ``ShipmentEvent.status`` <-> ``shipment_events.canonical_status`` (both
  nullable when the provider status needs review); timestamps are timezone-aware UTC.
"""

from collections.abc import Iterable
from decimal import Decimal

from app.db.models import Shipment as ShipmentRecord
from app.db.models import ShipmentEvent as ShipmentEventRecord
from app.domain.models.common import Address, Money, ShippingProviderCode
from app.domain.models.shipment import (
    Shipment,
    ShipmentEvent,
    ShipmentPackage,
    ShipmentStatus,
)
from app.providers.base.dto import CreateShipmentRequest, CreateShipmentResult
from app.repositories.shipping import AddressRecord, NewPackage, NewShipment, NewShipmentEvent

DEFAULT_CURRENCY = "VND"


class MixedCurrencyError(ValueError):
    """A shipment's amounts use more than one currency; the schema stores one."""


def single_currency(amounts: Iterable[Money | None]) -> str:
    currencies = {m.currency for m in amounts if m is not None}
    if len(currencies) > 1:
        raise MixedCurrencyError(f"a shipment must use one currency, got {sorted(currencies)}")
    return currencies.pop() if currencies else DEFAULT_CURRENCY


def address_to_record(address: Address | None) -> AddressRecord | None:
    if address is None:
        return None
    return AddressRecord(
        name=address.name,
        phone=address.phone,
        address_line=address.address_line,
        ward=address.ward,
        district=address.district,
        province=address.province,
    )


def address_from_record(record: ShipmentRecord, prefix: str) -> Address | None:
    values = {
        name: getattr(record, f"{prefix}_{name}")
        for name in ("name", "phone", "address_line", "ward", "district", "province")
    }
    if not all(values[k] for k in ("name", "phone", "address_line", "province")):
        return None
    return Address(**values)


def new_shipment_from_request(
    request: CreateShipmentRequest,
    *,
    provider_id: int,
    status: ShipmentStatus,
    tracking_number: str | None = None,
    provider_status: str | None = None,
    estimated_fee: Money | None = None,
    shipping_account_id: int | None = None,
) -> NewShipment:
    """Repository input for a shipment request (before or after the provider call)."""
    currency = single_currency(
        [request.cod_amount, estimated_fee] + [p.declared_value for p in request.packages]
    )
    return NewShipment(
        order_id=request.order_id,
        provider_id=provider_id,
        shipping_account_id=shipping_account_id,
        tracking_number=tracking_number,
        service_code=request.service_code,
        status=status.value,
        provider_status=provider_status,
        sender=address_to_record(request.sender),
        receiver=address_to_record(request.receiver),
        packages=[
            NewPackage(
                weight_grams=p.weight_grams,
                length_cm=p.length_cm,
                width_cm=p.width_cm,
                height_cm=p.height_cm,
                description=p.description,
                declared_value=p.declared_value.amount if p.declared_value else None,
            )
            for p in request.packages
        ],
        cod_amount=request.cod_amount.amount if request.cod_amount else Decimal(0),
        currency=currency,
        estimated_fee=estimated_fee.amount if estimated_fee else None,
    )


def new_shipment_from_created(
    request: CreateShipmentRequest,
    result: CreateShipmentResult,
    *,
    provider_id: int,
    shipping_account_id: int | None = None,
    estimated_fee: Money | None = None,
) -> NewShipment:
    """Repository input for a shipment the provider has just created."""
    fee = estimated_fee or result.fee
    single_currency([request.cod_amount, result.fee, estimated_fee])
    return new_shipment_from_request(
        request,
        provider_id=provider_id,
        status=result.status,
        tracking_number=result.tracking_number,
        provider_status=result.provider_status,
        estimated_fee=fee,
        shipping_account_id=shipping_account_id,
    )


def new_event_from_domain(
    event: ShipmentEvent, *, webhook_event_id: int | None = None
) -> NewShipmentEvent:
    return NewShipmentEvent(
        canonical_status=event.status.value if event.status else None,
        occurred_at=event.occurred_at,
        occurred_at_raw=event.occurred_at_raw,
        received_at=event.received_at,
        provider_status=event.provider_status,
        provider_status_name=event.provider_status_name,
        requires_review=event.requires_review,
        provider_event_id=event.provider_event_id,
        description=event.description,
        location=event.location,
        webhook_event_id=webhook_event_id,
    )


def event_to_domain(
    record: ShipmentEventRecord, *, provider: ShippingProviderCode, tracking_number: str
) -> ShipmentEvent:
    return ShipmentEvent(
        provider=provider,
        tracking_number=tracking_number,
        status=ShipmentStatus(record.canonical_status) if record.canonical_status else None,
        occurred_at=record.occurred_at,
        occurred_at_raw=record.occurred_at_raw,
        received_at=record.received_at,
        provider_status=record.provider_status,
        provider_status_name=record.provider_status_name,
        provider_event_id=record.provider_event_id,
        requires_review=record.requires_review,
        description=record.description,
        location=record.location,
    )


def shipment_to_domain(
    record: ShipmentRecord, events: Iterable[ShipmentEventRecord] = ()
) -> Shipment:
    provider = ShippingProviderCode(record.provider.code)
    currency = record.currency

    def money(value: Decimal | None) -> Money | None:
        return None if value is None else Money(amount=value, currency=currency)

    fee = record.actual_fee if record.actual_fee is not None else record.estimated_fee
    return Shipment(
        order_id=record.order_id,
        provider=provider,
        status=ShipmentStatus(record.status),
        tracking_number=record.tracking_number,
        provider_status=record.provider_status,
        service_code=record.service_code,
        sender=address_from_record(record, "sender"),
        receiver=address_from_record(record, "receiver"),
        packages=[
            ShipmentPackage(
                weight_grams=p.weight_grams,
                length_cm=p.length_cm,
                width_cm=p.width_cm,
                height_cm=p.height_cm,
                description=p.description,
                declared_value=money(p.declared_value),
            )
            for p in record.packages
        ],
        cod_amount=money(record.cod_amount) if record.cod_amount else None,
        fee=money(fee),
        # Provider events always belong to a tracked shipment.
        events=[
            event_to_domain(e, provider=provider, tracking_number=record.tracking_number)
            for e in events
        ]
        if record.tracking_number
        else [],
        updated_at=record.updated_at,
    )
