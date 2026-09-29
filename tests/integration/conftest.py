"""Shared fixtures for integration tests."""

import pytest

from app.api.dependencies import get_application
from app.main import app
from app.webhooks.dependencies import get_vtp_webhook_processor


@pytest.fixture
def make_env(migrated_url):
    """Build an end-to-end environment (fake provider, real DB, durable webhook sink)."""
    from tests.integration.test_webhook_to_shipment import Env

    envs = []

    def build(**kwargs):
        env = Env(migrated_url, **kwargs)
        envs.append(env)
        app.dependency_overrides[get_application] = lambda: env.app
        app.dependency_overrides[get_vtp_webhook_processor] = lambda: env.processor
        return env

    yield build
    app.dependency_overrides.clear()
    for env in envs:
        env.engine.dispose()
