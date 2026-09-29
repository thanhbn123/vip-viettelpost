"""Maps application/provider errors to HTTP. Responses never carry stack traces,
credentials, SQL or request payloads; only a stable code and a short safe detail."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.providers.base.errors import (
    ProviderAuthError,
    ProviderRejectedError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.repositories.mappers import MixedCurrencyError
from app.services.finance import FinanceError, ReconciliationNotFoundError
from app.services.shipping_app import (
    DuplicateActiveShipmentError,
    InvalidShipmentStateError,
    OperationInProgressError,
    PersistenceAfterProviderError,
    ProviderDisabledError,
    ShipmentNotFoundError,
    UnsupportedProviderError,
)

logger = logging.getLogger("app.api.errors")

# (status, code, expose provider/app message?)
_MAPPING: list[tuple[type[BaseException], int, str, bool]] = [
    (ShipmentNotFoundError, 404, "shipment_not_found", True),
    (ReconciliationNotFoundError, 404, "reconciliation_not_found", True),
    (FinanceError, 422, "invalid_finance_operation", True),
    (UnsupportedProviderError, 404, "provider_not_supported", True),
    (ProviderDisabledError, 409, "provider_disabled", True),
    (DuplicateActiveShipmentError, 409, "duplicate_active_shipment", True),
    (InvalidShipmentStateError, 409, "invalid_shipment_state", True),
    (OperationInProgressError, 409, "operation_in_progress", True),
    (ProviderRequestError, 422, "invalid_provider_request", True),
    (MixedCurrencyError, 422, "mixed_currency", True),
    # Auth before Rejected (subclass): our credentials, not the caller's fault; hide detail.
    (ProviderAuthError, 502, "provider_auth_failed", False),
    (ProviderRejectedError, 422, "provider_rejected", True),
    (ProviderTimeoutError, 504, "provider_timeout", False),
    (ProviderUnavailableError, 503, "provider_unavailable", False),
    (ProviderResponseError, 502, "provider_bad_response", False),
    (PersistenceAfterProviderError, 500, "persistence_failed_after_provider_success", True),
    (NotImplementedError, 501, "not_implemented", True),
]

_GENERIC = {
    "provider_auth_failed": "the gateway could not authenticate with the provider",
    "provider_timeout": "the provider did not answer in time; the outcome is unknown",
    "provider_unavailable": "the provider is unavailable; retry later",
    "provider_bad_response": "the provider returned an unexpected response",
}


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _handler(status: int, code: str, expose: bool):
    async def handle(request: Request, exc: BaseException) -> JSONResponse:
        detail = str(exc)[:300] if expose else _GENERIC.get(code, code)
        if status >= 500:
            logger.warning(
                "request %s failed: %s (%s)", request_id_of(request), code, type(exc).__name__
            )
        return JSONResponse(
            status_code=status,
            content={"error": code, "detail": detail, "request_id": request_id_of(request)},
        )

    return handle


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("request %s failed with an unexpected error", request_id_of(request))
    rid = request_id_of(request)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "unexpected error", "request_id": rid},
        # This response bypasses the request-id middleware; set the header here.
        headers={"X-Request-ID": rid} if rid else None,
    )


def install_error_handlers(app: FastAPI) -> None:
    for exc_type, status, code, expose in _MAPPING:
        app.add_exception_handler(exc_type, _handler(status, code, expose))
    app.add_exception_handler(Exception, _unexpected)
