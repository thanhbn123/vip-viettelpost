import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors import install_error_handlers
from app.api.health import router as health_router
from app.api.routes import router as api_router
from app.core.config import settings
from app.core.logging import configure_logging, request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

configure_logging(
    level=settings.log_level,
    fmt=settings.log_format,
    secrets=[settings.vtp_password, settings.vtp_token, settings.webhook_shared_secret],
)

app = FastAPI(
    title="VIP Shipping Gateway",
    version="0.1.0",
)
install_error_handlers(app)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    # Oversized API bodies are refused before parsing. The webhook route enforces its
    # own (smaller) limit and is excluded here.
    declared = request.headers.get("content-length")
    if (
        request.url.path.startswith("/api/")
        and "/webhooks/" not in request.url.path
        and declared is not None
        and declared.isdigit()
        and int(declared) > settings.api_max_body_bytes
    ):
        response = JSONResponse(
            status_code=413,
            content={"error": "payload_too_large", "detail": "request body too large"},
        )
    else:
        response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.middleware("http")
async def request_id(request: Request, call_next):
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    # Accept a caller id only if short and printable; otherwise mint one.
    rid = incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex
    request.state.request_id = rid
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers[REQUEST_ID_HEADER] = rid
    return response


app.include_router(health_router, tags=["health"])
app.include_router(api_router, prefix="/api/v1")
