"""Keep secrets out of persisted JSON (webhook payloads, headers, audit diffs).

Two rules, deliberately different:

* Headers are stored through an ALLOWLIST. Forgetting a header name only
  loses a debug hint; a denylist that forgets one leaks a credential.
* Payload / audit JSON is free-form, so an allowlist is impossible there;
  keys that look secret are replaced by ``[REDACTED]`` recursively.
"""

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

SAFE_HEADER_NAMES = frozenset(
    {
        "content-type",
        "content-length",
        "user-agent",
        "x-request-id",
        "x-correlation-id",
        "x-forwarded-for",
        "x-real-ip",
    }
)

# Long markers match anywhere in the normalised key ("vtpToken", "API-KEY").
_SECRET_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "authorization",
    "authorisation",
    "privatekey",
    "credential",
    "cookie",
    "signature",
)
# Short markers only as a whole word, so "shipping" does not match "pin".
_SECRET_WORDS = frozenset({"pass", "pwd", "otp", "pin", "key", "auth"})


def is_secret_key(key: str) -> bool:
    normalised = re.sub(r"[^a-z0-9]", "", key.lower())
    if any(marker in normalised for marker in _SECRET_MARKERS):
        return True
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key).lower()
    return any(w in _SECRET_WORDS for w in re.split(r"[^a-z0-9]+", words))


def safe_headers(headers: Mapping[str, str] | None) -> dict[str, str] | None:
    if headers is None:
        return None
    return {k.lower(): v for k, v in headers.items() if k.lower() in SAFE_HEADER_NAMES}


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if isinstance(k, str) and is_secret_key(k) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value
