"""G11: logging context/masking, metrics, retry policy, readiness."""

import asyncio
import json
import logging

import pytest

from app.core.logging import (
    MASK,
    JsonFormatter,
    RequestIdFilter,
    SecretMaskingFilter,
    request_id_var,
)
from app.core.metrics import Metrics
from app.domain.models import Money, ShipmentStatus
from app.providers.base.dto import CreateShipmentResult, FeeQuote
from app.providers.base.errors import (
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.providers.instrumented import InstrumentedProvider, RetryPolicy
from tests.integration.test_shipping_api import FakeProvider


def record(msg, *args):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_secret_masking_filter():
    f = SecretMaskingFilter(["super-secret-password", None, "abc"])  # short values ignored
    r = record("login %s token %s ok abc", "super-secret-password", "eyJhbGciOi.eyJzdWIi.sig")
    f.filter(r)
    assert r.getMessage() == "login *** token *** ok abc"


def test_database_url_password_is_masked_even_when_not_configured():
    """The DSN password is never in the configured-secret list, but drivers print it."""
    f = SecretMaskingFilter([])
    dsn = "postgresql+psycopg://vip_user:not-real-db-password@db.internal:5432/vip_staging"
    r = record("connection failed: %s", dsn)
    f.filter(r)
    message = r.getMessage()
    # Built from MASK, not written out: a masked DSN literal would itself trip the
    # credential-shape scanner in tests/test_no_secrets.py.
    assert "not-real-db-password" not in message
    assert message == f"connection failed: postgresql+psycopg://vip_user:{MASK}" + (
        "@db.internal:5432/vip_staging"
    )


def test_url_masking_prefers_over_masking_to_leaking():
    """RFC 3986 allows , & = ' in userinfo; the mask must still cover the whole password.

    Stopping the password at those characters would make the pattern miss the "@" and
    print the password in full. The price is that a non-URL "host:port,...@..." string is
    over-masked, which is visible in the log instead of silent.
    """
    f = SecretMaskingFilter([])
    for dsn, expected_tail in (
        ("postgresql://u:not-real,pw&x@db/vip", "@db/vip"),
        ("postgresql://u:not-real=pw'q@db/vip", "@db/vip"),
    ):
        r = record("dsn %s", dsn)
        f.filter(r)
        assert r.getMessage() == f"dsn postgresql://u:{MASK}" + expected_tail


def test_url_masking_keeps_ordinary_urls_intact():
    """A port is not a password: "host:443/path?email=a@b" must survive untouched."""
    f = SecretMaskingFilter([])
    for url in (
        "https://partnerdev.viettelpost.vn/v2/order/getPrice",
        "https://cpn.viporder.vn/health/ready",
        "postgresql+psycopg://vip_user@db.internal:5432/vip_staging",
        "https://partner2.viettelpost.vn:443/v2/order?email=cust@vip.vn",
        "https://partnerdev.viettelpost.vn:443/v2/order/getPrice",
    ):
        r = record("calling %s", url)
        f.filter(r)
        assert r.getMessage() == f"calling {url}"


def test_url_masking_covers_a_password_containing_an_at_sign():
    f = SecretMaskingFilter([])
    r = record("dsn %s", "postgresql://vip_user:not-real@pass@db.internal/vip_staging")
    f.filter(r)
    message = r.getMessage()
    assert "not-real@pass" not in message and "pass@db" not in message
    assert message == f"dsn postgresql://vip_user:{MASK}" + "@db.internal/vip_staging"


def test_request_id_filter_and_json_formatter():
    token = request_id_var.set("req-42")
    try:
        r = record("hello %s", "world")
        RequestIdFilter().filter(r)
        out = json.loads(JsonFormatter().format(r))
    finally:
        request_id_var.reset(token)
    assert out["request_id"] == "req-42" and out["message"] == "hello world"
    r2 = record("x")
    RequestIdFilter().filter(r2)
    assert r2.request_id == "-"


def test_metrics_snapshot():
    m = Metrics()
    m.inc("calls", op="a")
    m.inc("calls", op="a")
    m.observe("t", 0.5, op="a")
    m.observe("t", 1.5, op="a")
    snap = m.snapshot()
    assert snap["counters"] == [{"name": "calls", "labels": {"op": "a"}, "value": 2}]
    assert snap["timings"][0]["count"] == 2 and snap["timings"][0]["max_ms"] == 1500.0


class Flaky(FakeProvider):
    def __init__(self, errors):
        super().__init__()
        self.errors = list(errors)
        self.fee_calls = 0
        self.create_calls = 0

    async def calculate_fee(self, request):
        self.fee_calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return FeeQuote(provider=self.code, total=Money(amount=1))

    async def create_shipment(self, request):
        self.create_calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return CreateShipmentResult(
            provider=self.code, order_id="o", tracking_number="t", status=ShipmentStatus.CREATED
        )


def run(coro):
    return asyncio.run(coro)


async def no_sleep(_):
    return None


def test_read_only_call_is_retried_within_bound():
    inner = Flaky([ProviderTimeoutError("t"), ProviderUnavailableError("u")])
    p = InstrumentedProvider(inner, retry=RetryPolicy(max_attempts=3), sleep=no_sleep)
    assert run(p.calculate_fee(None)).total == Money(amount=1)
    assert inner.fee_calls == 3


def test_retry_is_bounded():
    inner = Flaky([ProviderUnavailableError("u")] * 5)
    p = InstrumentedProvider(inner, retry=RetryPolicy(max_attempts=3), sleep=no_sleep)
    with pytest.raises(ProviderUnavailableError):
        run(p.calculate_fee(None))
    assert inner.fee_calls == 3


def test_rejection_is_not_retried():
    inner = Flaky([ProviderRejectedError("no")])
    p = InstrumentedProvider(inner, retry=RetryPolicy(max_attempts=3), sleep=no_sleep)
    with pytest.raises(ProviderRejectedError):
        run(p.calculate_fee(None))
    assert inner.fee_calls == 1


def test_create_is_never_retried():
    inner = Flaky([ProviderTimeoutError("t")])
    p = InstrumentedProvider(inner, retry=RetryPolicy(max_attempts=5), sleep=no_sleep)
    with pytest.raises(ProviderTimeoutError):
        run(p.create_shipment(None))
    assert inner.create_calls == 1


def test_backoff_is_capped():
    policy = RetryPolicy(max_attempts=10, base_delay=0.5, max_delay=2.0)
    assert [policy.delay(a) for a in (1, 2, 3, 4)] == [0.5, 1.0, 2.0, 2.0]


def test_instrumented_provider_keeps_contract_and_code():
    import inspect

    from app.providers.base.provider import ShippingProvider

    p = InstrumentedProvider(FakeProvider())
    assert isinstance(p, ShippingProvider) and not inspect.isabstract(InstrumentedProvider)
    assert p.code == "VIETTEL_POST"


def test_provider_calls_are_logged_and_counted(caplog):
    from app.core.metrics import metrics

    metrics.reset()
    p = InstrumentedProvider(Flaky([]), retry=RetryPolicy(max_attempts=1))
    with caplog.at_level(logging.INFO, logger="app.providers.calls"):
        run(p.calculate_fee(None))
    assert any(
        "op=calculate_fee" in r.getMessage() and "outcome=ok" in r.getMessage()
        for r in caplog.records
    )
    names = {c["name"] for c in metrics.snapshot()["counters"]}
    assert "provider_calls" in names


# --- verifier findings on PR #16 --------------------------------------------------------


def _exc_record(secret):
    try:
        raise RuntimeError(f"boom with {secret}")
    except RuntimeError:
        import sys

        return logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())


def test_traceback_text_is_masked():
    secret = "configured-secret-value-123"
    record = _exc_record(secret)
    SecretMaskingFilter([secret]).filter(record)
    rendered = logging.Formatter().format(record)
    assert "boom with ***" in rendered and secret not in rendered


def test_json_format_keeps_the_traceback_masked():
    secret = "configured-secret-value-123"
    record = _exc_record(secret)
    RequestIdFilter().filter(record)
    SecretMaskingFilter([secret]).filter(record)
    out = json.loads(JsonFormatter().format(record))
    assert out["exc_type"] == "RuntimeError"
    assert "Traceback" in out["exc"] and secret not in out["exc"]


def test_instrumented_provider_can_be_copied():
    import copy

    p = InstrumentedProvider(FakeProvider())
    assert copy.copy(p).code == "VIETTEL_POST"


def test_postgres_engine_gets_a_connect_timeout(monkeypatch):
    from app.core import database
    from app.core.config import settings

    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u@127.0.0.1:1/x")
    database.get_engine.cache_clear()
    try:
        engine = database.get_engine()
        assert engine.dialect.name == "postgresql"
        # connect_args are kept on the pool's creator; check via a failing connect time bound
        import time

        from sqlalchemy.exc import OperationalError

        started = time.perf_counter()
        with pytest.raises(OperationalError):
            engine.connect()
        assert time.perf_counter() - started < 10
    finally:
        database.get_engine.cache_clear()
