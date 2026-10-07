"""Dependency injection for the shipping API. Tests override ``get_application``."""

from functools import lru_cache

from fastapi import Request

from app.core.container import get_providers
from app.core.database import get_session_factory
from app.repositories.shipping import Actor, ActorType
from app.services.finance import ShipmentFinance
from app.services.operations import ShipmentOperations
from app.services.shipping_app import ShippingApplication
from app.webhooks.dependencies import get_webhook_applier


@lru_cache(maxsize=1)
def get_application() -> ShippingApplication:
    return ShippingApplication(
        get_providers(), get_session_factory(), webhook_applier=get_webhook_applier()
    )


def get_actor(request: Request) -> Actor:
    """The authenticated API key id (set by ``require_api_key``) is the audit actor."""
    key_id = getattr(request.state, "api_key_id", None)
    return Actor(ActorType.SYSTEM, f"apikey:{key_id}" if key_id else "api")


@lru_cache(maxsize=1)
def get_operations() -> ShipmentOperations:
    return ShipmentOperations(get_session_factory())


@lru_cache(maxsize=1)
def get_finance() -> ShipmentFinance:
    return ShipmentFinance(get_session_factory())
