"""Logging: request id on every record, secret masking, optional JSON output (G11).

Masking is a safety net, not the primary control: code must still never log secrets.
It masks JWT-shaped strings and every configured secret value (VTP password/token,
webhook secret, API keys) wherever they appear in a formatted message.
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
        return _JWT.sub(MASK, text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: keep the record, do not crash logging
            return True
        masked = self.mask(message)
        if masked != message or record.args:
            record.msg, record.args = masked, None
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
