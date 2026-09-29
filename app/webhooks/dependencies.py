"""Wiring for the webhook route.

The stores wired here are the in-memory fakes from ``app.webhooks.stores``: this branch
has no database. Before any staging/production use they must be replaced by durable
implementations (see docs/SECURITY.md, "Webhook"), otherwise idempotency does not
survive a restart or span several workers.
"""

from functools import lru_cache

from app.core.config import settings
from app.webhooks.processor import WebhookProcessor
from app.webhooks.stores import InMemoryIdempotencyStore, InMemoryWebhookEventStore


@lru_cache(maxsize=1)
def get_vtp_webhook_processor() -> WebhookProcessor:
    return WebhookProcessor(
        shared_secret=settings.webhook_shared_secret,
        idempotency_store=InMemoryIdempotencyStore(),
        event_store=InMemoryWebhookEventStore(),
    )
