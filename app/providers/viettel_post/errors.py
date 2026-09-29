"""Errors raised by the Viettel Post adapter.

No error message may contain a credential: username, password or token.
Provider messages are passed through ``redact`` before they reach an exception.
"""

import re
from collections.abc import Iterable

_MASK = "***"
# Tokens in the official samples are JWT-shaped (``eyJ...``); mask any that leak into text.
_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*){1,2}")
_MAX_MESSAGE_LENGTH = 200


def redact(text: str, secrets: Iterable[str | None] = ()) -> str:
    """Return ``text`` with every known secret value and JWT-shaped string masked."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, _MASK)
    text = _JWT_PATTERN.sub(_MASK, text)
    if len(text) > _MAX_MESSAGE_LENGTH:
        text = text[:_MAX_MESSAGE_LENGTH] + "..."
    return text


class ViettelPostError(Exception):
    """Base class for every error raised by the Viettel Post adapter."""


class ViettelPostTimeoutError(ViettelPostError):
    """The request did not complete within the configured timeout."""


class ViettelPostNetworkError(ViettelPostError):
    """The request failed before an HTTP response was received."""


class ViettelPostHTTPError(ViettelPostError):
    """Viettel Post answered with an HTTP error status."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class ViettelPostClientError(ViettelPostHTTPError):
    """HTTP 4xx."""


class ViettelPostServerError(ViettelPostHTTPError):
    """HTTP 5xx."""


class ViettelPostInvalidResponseError(ViettelPostError):
    """The response body is not valid JSON or does not have the documented shape."""


class ViettelPostBusinessError(ViettelPostError):
    """Viettel Post rejected the request: the envelope carries ``"error": true``."""

    def __init__(self, message: str, *, provider_status: int | None = None) -> None:
        super().__init__(message)
        self.provider_status = provider_status


class ViettelPostAuthError(ViettelPostBusinessError):
    """Credentials or token were rejected (missing, invalid or expired)."""
