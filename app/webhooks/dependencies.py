"""Wiring for the webhook route: durable SQL sink on the configured database."""

from functools import lru_cache

from app.core.config import settings
from app.core.database import get_session_factory
from app.providers.viettel_post.events import resolve_timezone
from app.webhooks.processor import WebhookProcessor
from app.webhooks.sql_sink import SqlWebhookSink


@lru_cache(maxsize=1)
def get_vtp_webhook_processor() -> WebhookProcessor:
    return WebhookProcessor(
        shared_secret=settings.webhook_shared_secret,
        sink=SqlWebhookSink(
            get_session_factory(),
            event_timezone=resolve_timezone(settings.vtp_webhook_timezone),
        ),
        max_body_bytes=settings.webhook_max_body_bytes,
    )
