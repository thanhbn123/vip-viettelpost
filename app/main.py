import uuid

from fastapi import FastAPI, Request

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
