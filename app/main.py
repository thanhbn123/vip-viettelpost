import uuid

from fastapi import Depends, FastAPI, Request

from app.api.auth import parse_api_keys, require_api_key
from app.api.body_limit import BodyLimitMiddleware
from app.api.errors import SECURITY_HEADERS, install_error_handlers
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

# Refuse to boot with a malformed API_KEYS (verifier PR #18 finding 5).
parse_api_keys(settings.api_keys)

app = FastAPI(
    title="VIP Shipping Gateway",
    version="0.1.0",
    # No public schema/docs (verifier PR #18 finding 2): /openapi.json is served below
    # behind the API key; Swagger/ReDoc UIs are not served.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
install_error_handlers(app)


@app.middleware("http")
async def security_headers(request: Request, call_next):
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


@app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_api_key)])
def openapi_schema():
    return app.openapi()


def _body_limit(path: str) -> int | None:
    if not path.startswith("/api/"):
        return None
    if "/webhooks/" in path:
        return settings.webhook_max_body_bytes
    return settings.api_max_body_bytes


# Outermost layer: counts real bytes before routing and authentication.
app.add_middleware(BodyLimitMiddleware, limit_for=_body_limit)
