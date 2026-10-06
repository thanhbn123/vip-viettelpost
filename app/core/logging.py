"""Logging: request id on every record, secret masking, optional JSON output (G11).

Masking is a safety net, not the primary control: code must still never log secrets.
It masks JWT-shaped strings, credentials embedded in a URL (the DATABASE_URL password)
and every configured secret value (VTP password/token, webhook secret) wherever they
appear in a formatted message or traceback. Raw API keys are never configured (only
their SHA-256), so they are not in this list.
"""

import contextvars
import json
import logging
import re
from collections.abc import Iterable

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*){1,2}")
# Credentials embedded in a URL — in practice the password in DATABASE_URL, which the
# configured-secret list never sees. SQLAlchemy and psycopg print the DSN in connection
# errors, so without this the password reaches the log on the first failed connect.
# The password stops at "/", "?" and "#" (a DSN percent-encodes those), which keeps
# "https://host:443/v2/order?email=a@b" — port, path and query — intact, and is greedy up
# to the last "@" before them, so a password containing "@" is masked whole.
#
# Everything else is allowed in the password on purpose, even though the pattern then runs
# over text that is not a URL: a "host:port" followed on the same line by a comma and an
# address loses the port and everything up to that address. That
# over-masks, which is ugly but visible. Narrowing the class to stop at "," & " \' = would
# fix the cosmetics and LEAK: RFC 3986 allows those in userinfo, so for a password like
# "pa,ss&x" the pattern would no longer reach the "@", match nothing, and print the
# password in full. A mask must fail towards masking too much (CLAUDE.md 12.2).
_URL_CREDENTIALS = re.compile(r"(?P<head>://[^:/?#\[\]@\s]+:)[^\s/?#]+(?=@)")
MASK = "***"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class SecretMaskingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str | None] = ()) -> None:
        super().__init__()
        # Short values would mask ordinary words; configured secrets are long in practice.
        self._secrets = sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True)

    def mask(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        text = _URL_CREDENTIALS.sub(rf"\g<head>{MASK}", text)
        return _JWT.sub(MASK, text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: keep the record, do not crash logging
            return True
        masked = self.mask(message)
        if masked != message or record.args:
            record.msg, record.args = masked, None
        # Tracebacks too (verifier PR #16): render once, mask, and let formatters reuse it.
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.mask(record.exc_text)
        if record.stack_info:
            record.stack_info = self.mask(record.stack_info)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            # exc_text is already masked by SecretMaskingFilter when it ran.
            payload["exc"] = record.exc_text or self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, level: str, fmt: str, secrets: Iterable[str | None]) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.addFilter(SecretMaskingFilter(secrets))
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
