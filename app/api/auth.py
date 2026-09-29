"""Caller authentication for the shipping API (CR-SHP-001 G12, D-033).

* Header ``X-API-Key``. Configuration ``API_KEYS`` holds only SHA-256 digests:
  ``"<key_id>:<sha256 hex>,<key_id2>:<sha256 hex>"``. Raw keys never live in config,
  logs or the database; generate one with ``python -m app.tools.api_key <key_id>``.
* Constant-time comparison. Fail closed: no keys configured -> 503 on protected routes.
* The key id becomes the audit actor (``SYSTEM`` / ``apikey:<key_id>``).
* Not applied to the provider webhook (authenticated by its body TOKEN) or to
  ``/health`` and ``/health/ready``.
"""

import hashlib
import hmac
import re
from functools import lru_cache

from fastapi import Request

from app.core.config import settings

API_KEY_HEADER = "X-API-Key"
_ENTRY = re.compile(r"^([A-Za-z0-9_.-]{1,64}):([0-9a-f]{64})$")
MIN_KEY_LENGTH = 32


class AuthNotConfiguredError(Exception):
    """No API key is configured: protected routes stay closed."""


class UnauthenticatedError(Exception):
    """Missing or unknown API key."""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@lru_cache(maxsize=8)
def parse_api_keys(raw: str | None) -> tuple[tuple[str, str], ...]:
    """Parse ``API_KEYS``; raises ValueError on a malformed entry (fail at startup)."""
    if not raw or not raw.strip():
        return ()
    entries = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        match = _ENTRY.match(part)
        if not match:
            raise ValueError("API_KEYS entries must look like <key_id>:<sha256 hex>")
        entries.append((match.group(1), match.group(2)))
    ids = [key_id for key_id, _ in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("API_KEYS contains a duplicate key id")
    return tuple(entries)


async def require_api_key(request: Request) -> str:
    keys = parse_api_keys(settings.api_keys)
    if not keys:
        raise AuthNotConfiguredError("API authentication is not configured")
    presented = request.headers.get(API_KEY_HEADER)
    if not presented:
        raise UnauthenticatedError("missing API key")
    digest = hash_key(presented)
    matched = None
    for key_id, expected in keys:  # compare against every entry: no early exit timing
        if hmac.compare_digest(digest, expected):
            matched = key_id
    if matched is None:
        raise UnauthenticatedError("invalid API key")
    request.state.api_key_id = matched
    return matched
