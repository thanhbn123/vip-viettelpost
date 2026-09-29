"""Dependency injection for the shipping API. Tests override ``get_application``."""

from functools import lru_cache

from fastapi import Request

from app.core.container import get_providers
from app.core.database import get_session_factory
from app.repositories.shipping import Actor, ActorType
from app.services.shipping_app import ShippingApplication
from app.webhooks.dependencies import get_webhook_applier


@lru_cache(maxsize=1)
def get_application() -> ShippingApplication:
    return ShippingApplication(
        get_providers(), get_session_factory(), webhook_applier=get_webhook_applier()
    )


def get_actor(request: Request) -> Actor:
    # No caller authentication yet (G12): mutations are attributed to the API itself.
    return Actor(ActorType.SYSTEM, "api")
