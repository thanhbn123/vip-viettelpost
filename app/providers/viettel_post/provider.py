from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.providers.base.provider import ShippingProvider
from app.providers.viettel_post import mapping
from app.providers.viettel_post.auth import ViettelPostAuth
from app.providers.viettel_post.client import ViettelPostClient, check_envelope
from app.providers.viettel_post.errors import ViettelPostAuthError

T = TypeVar("T")


class ViettelPostProvider(ShippingProvider):
    """Viettel Post adapter. Endpoints follow https://partner2.viettelpost.vn/document.

    Payloads keep the baseline ``dict`` contract; see docs/VIETTEL_POST_INTEGRATION.md for the
    snake_case keys each method accepts.
    """

    code = "VIETTEL_POST"

    def __init__(
        self,
        client: ViettelPostClient | None = None,
        auth: ViettelPostAuth | None = None,
    ) -> None:
        self.client = client or ViettelPostClient()
        self.auth = auth or ViettelPostAuth(self.client)

    async def _with_token(self, call: Callable[[str], Awaitable[T]]) -> T:
        """Run ``call`` with a token; on a token rejection, refresh once when possible."""
        token = await self.auth.get_token()
        try:
            return await call(token)
        except ViettelPostAuthError:
            self.auth.invalidate()
            if not self.auth.can_refresh:
                raise
            return await call(await self.auth.get_token())

    async def authenticate(self) -> str:
        return await self.auth.get_token()

    async def get_services(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        body = mapping.build_get_services_request(payload)
        path = mapping.GET_SERVICES_PATH

        async def call(token: str) -> Any:
            response = await self.client.request("POST", path, token=token, json=body)
            if isinstance(response, dict):
                # Not the documented array: surface a rejection envelope as a business error.
                check_envelope(response, "POST", path, secrets=[token])
            return response

        return mapping.parse_services_response(await self._with_token(call))

    async def calculate_fee(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = mapping.build_calculate_fee_request(payload)
        envelope = await self._with_token(
            lambda token: self.client.request_envelope(
                "POST", mapping.CALCULATE_FEE_PATH, token=token, json=body
            )
        )
        return mapping.parse_fee_response(envelope)

    async def create_shipment(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = mapping.build_create_order_request(payload)
        envelope = await self._with_token(
            lambda token: self.client.request_envelope(
                "POST", mapping.CREATE_ORDER_PATH, token=token, json=body
            )
        )
        return mapping.parse_create_order_response(envelope)

    async def get_shipment(self, tracking_number: str) -> dict[str, Any]:
        # TODO: the Partner docs (partner2.viettelpost.vn/document, checked 2026-09-29) list no
        # order lookup/tracking API; status arrives by webhook. Implement only once Viettel Post
        # publishes or confirms an official lookup contract.
        raise NotImplementedError(
            "Viettel Post chưa công bố API tra cứu vận đơn trong tài liệu Partner chính thức."
        )

    async def cancel_shipment(self, tracking_number: str) -> dict[str, Any]:
        body = mapping.build_cancel_request(tracking_number)
        envelope = await self._with_token(
            lambda token: self.client.request_envelope(
                "POST", mapping.UPDATE_ORDER_STATUS_PATH, token=token, json=body
            )
        )
        return mapping.parse_cancel_response(envelope, tracking_number)

    async def handle_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Out of scope for W-SHP-02: kept unchanged for compatibility.
        return {"accepted": True, "provider": self.code, "payload": payload}
