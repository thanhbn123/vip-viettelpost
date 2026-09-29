"""Viettel Post Partner authentication.

Contract verified against https://partner2.viettelpost.vn/document/token-authen:

1. ``POST /v2/user/Login`` with ``{"USERNAME", "PASSWORD"}`` returns a short-lived token
   in ``data.token``. The documentation does not state how long it lives.
2. ``POST /v2/user/ownerconnect`` with header ``Token: <token from step 1>`` and the same
   ``{"USERNAME", "PASSWORD"}`` returns a long-lived token in ``data.token``, documented as
   valid for 1 year.
3. ``POST /v2/user/LoginVTP`` with ``{"token": <secret token copied from viettelpost.vn>}``
   returns a Partner token in ``data.token``.

The response field ``data.expired`` is ``0`` in every sample and its meaning is not documented,
so it is kept as-is and never interpreted as an expiry.

Never log, return in an error, or put in ``repr`` any username, password or token.
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.providers.viettel_post.client import ViettelPostClient
from app.providers.viettel_post.errors import ViettelPostAuthError, ViettelPostInvalidResponseError

LOGIN_PATH = "/v2/user/Login"
OWNER_CONNECT_PATH = "/v2/user/ownerconnect"
LOGIN_VTP_PATH = "/v2/user/LoginVTP"


@dataclass(frozen=True)
class ViettelPostAuthResult:
    """Internal auth outcome. ``token`` is hidden from ``repr`` and must stay in the adapter."""

    token: str = field(repr=False)
    user_id: int | None = None
    partner: int | None = None
    long_term: bool = False
    provider_expired_field: Any = None


def _parse_auth_envelope(
    envelope: dict[str, Any], path: str, *, long_term: bool
) -> ViettelPostAuthResult:
    data = envelope.get("data")
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise ViettelPostInvalidResponseError(
            f"Viettel Post POST {path} response has no data.token"
        )
    return ViettelPostAuthResult(
        token=token,
        user_id=data.get("userId"),
        partner=data.get("partner"),
        long_term=long_term,
        provider_expired_field=data.get("expired"),
    )


class ViettelPostAuth:
    def __init__(
        self,
        client: ViettelPostClient | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        static_token: str | None = None,
    ) -> None:
        self.client = client or ViettelPostClient()
        self._username = username if username is not None else settings.vtp_username
        self._password = password if password is not None else settings.vtp_password
        self._static_token = static_token if static_token is not None else settings.vtp_token
        self._cached: ViettelPostAuthResult | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.client.base_url!r})"

    async def login(self, username: str, password: str) -> ViettelPostAuthResult:
        """Step 1: short-lived token from Partner account credentials."""
        envelope = await self.client.request_envelope(
            "POST",
            LOGIN_PATH,
            json={"USERNAME": username, "PASSWORD": password},
            secrets=[username, password],
        )
        return _parse_auth_envelope(envelope, LOGIN_PATH, long_term=False)

    async def owner_connect(
        self, token: str, username: str, password: str
    ) -> ViettelPostAuthResult:
        """Step 2: long-lived token (documented 1 year), or a delegated token when
        ``token`` belongs to another account that grants access to ``username``."""
        envelope = await self.client.request_envelope(
            "POST",
            OWNER_CONNECT_PATH,
            token=token,
            json={"USERNAME": username, "PASSWORD": password},
            secrets=[username, password],
        )
        return _parse_auth_envelope(envelope, OWNER_CONNECT_PATH, long_term=True)

    async def login_vtp(self, vtp_secret_token: str) -> ViettelPostAuthResult:
        """Exchange a secret token created on viettelpost.vn for a Partner token."""
        envelope = await self.client.request_envelope(
            "POST",
            LOGIN_VTP_PATH,
            json={"token": vtp_secret_token},
            secrets=[vtp_secret_token],
        )
        return _parse_auth_envelope(envelope, LOGIN_VTP_PATH, long_term=False)

    async def authenticate(self) -> ViettelPostAuthResult:
        """Return a usable token: a configured static token, or Login then ownerconnect."""
        if self._cached is not None:
            return self._cached
        if self._static_token:
            self._cached = ViettelPostAuthResult(token=self._static_token, long_term=True)
            return self._cached
        if not self._username or not self._password:
            raise ViettelPostAuthError(
                "Viettel Post credentials are not configured (VTP_TOKEN or VTP_USERNAME/VTP_PASSWORD)"
            )
        short = await self.login(self._username, self._password)
        self._cached = await self.owner_connect(short.token, self._username, self._password)
        return self._cached

    async def get_token(self) -> str:
        return (await self.authenticate()).token

    def invalidate(self) -> None:
        """Forget the cached token, e.g. after Viettel Post answers ``Token invalid``."""
        self._cached = None

    @property
    def can_refresh(self) -> bool:
        """True when a rejected token can be replaced without operator action.

        A configured static token is always reused as-is, so it cannot be refreshed.
        """
        return not self._static_token and bool(self._username and self._password)
