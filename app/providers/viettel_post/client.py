"""HTTP client for the Viettel Post Partner API.

Contract verified against https://partner2.viettelpost.vn/document/environment-parameter:
- every authenticated call sends the token in a header named ``Token`` (not ``Authorization``);
- ``Content-Type: application/json;charset=UTF-8``;
- responses use the envelope ``{"status", "error", "message", "data"}``,
  with ``error: false`` on success and ``error: true`` on rejection.
"""

import json as jsonlib
from collections.abc import Iterable
from typing import Any

import httpx

from app.core.config import settings
from app.providers.viettel_post.errors import (
    ViettelPostAuthError,
    ViettelPostBusinessError,
    ViettelPostClientError,
    ViettelPostInvalidResponseError,
    ViettelPostNetworkError,
    ViettelPostServerError,
    ViettelPostTimeoutError,
    redact,
)

TOKEN_HEADER = "Token"
CONTENT_TYPE = "application/json;charset=UTF-8"
DEFAULT_TIMEOUT_SECONDS = 20.0

# Messages listed as token/credential failures in the official error table.
AUTH_ERROR_MESSAGES = frozenset(
    {
        "Header Token is required",
        "Token invalid",
        "Token invalid or expired",
        "Invalid owner account or password!",
    }
)

_NOT_JSON = object()


def _message_text(message: Any) -> str:
    # The error table shows ``message`` as a list on failure and a string on success.
    if isinstance(message, list):
        return "; ".join(str(item) for item in message)
    return "" if message is None else str(message)


def _decode(response: httpx.Response) -> Any:
    if not response.content:
        return _NOT_JSON
    try:
        return jsonlib.loads(response.content)
    except ValueError:
        return _NOT_JSON


class ViettelPostClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.vtp_base_url).rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        # Created lazily so that building the provider at import time opens no connection.
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, transport=self._transport)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def headers(self, token: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": CONTENT_TYPE, "Accept": "application/json"}
        if token:
            headers[TOKEN_HEADER] = token
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: Any = None,
        secrets: Iterable[str | None] = (),
    ) -> Any:
        """Send one request and return the decoded JSON body.

        ``secrets`` are extra values (e.g. a password in the body) masked from any error text.
        The request body is never included in an error.
        """
        hidden = [token, *secrets]
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = await self._http().request(
                method, url, headers=self.headers(token), json=json
            )
        except httpx.TimeoutException as exc:
            raise ViettelPostTimeoutError(
                f"Viettel Post {method} {path} timed out after {self.timeout}s"
            ) from exc
        except httpx.TransportError as exc:
            raise ViettelPostNetworkError(
                f"Viettel Post {method} {path} network error: {type(exc).__name__}"
            ) from exc

        body = _decode(response)

        if response.status_code >= 400:
            text = f"Viettel Post {method} {path} returned HTTP {response.status_code}"
            if isinstance(body, dict):
                detail = redact(_message_text(body.get("message")), hidden)
                if detail:
                    text = f"{text}: {detail}"
            if response.status_code >= 500:
                raise ViettelPostServerError(text, status_code=response.status_code)
            raise ViettelPostClientError(text, status_code=response.status_code)

        if body is _NOT_JSON:
            raise ViettelPostInvalidResponseError(
                f"Viettel Post {method} {path} returned a body that is not valid JSON"
            )
        return body

    async def request_envelope(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: Any = None,
        secrets: Iterable[str | None] = (),
    ) -> dict[str, Any]:
        """Send a request whose response uses the documented envelope and return it.

        Raises ``ViettelPostBusinessError`` (``ViettelPostAuthError`` for token or credential
        failures) when the envelope carries ``error: true``.
        """
        body = await self.request(method, path, token=token, json=json, secrets=secrets)
        return check_envelope(body, method, path, secrets=[token, *secrets])


def check_envelope(
    body: Any, method: str, path: str, *, secrets: Iterable[str | None] = ()
) -> dict[str, Any]:
    if not isinstance(body, dict) or "error" not in body:
        raise ViettelPostInvalidResponseError(
            f"Viettel Post {method} {path} response lacks the documented envelope"
        )
    if body["error"] is not False:
        message = _message_text(body.get("message"))
        status = body.get("status")
        text = f"Viettel Post {method} {path} rejected the request: {redact(message, secrets)}"
        error_cls = (
            ViettelPostAuthError if message in AUTH_ERROR_MESSAGES else ViettelPostBusinessError
        )
        raise error_cls(text, provider_status=status if isinstance(status, int) else None)
    return body
