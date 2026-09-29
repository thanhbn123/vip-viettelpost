import uuid

from fastapi import FastAPI, Request

from app.api.errors import install_error_handlers
from app.api.routes import router as api_router

REQUEST_ID_HEADER = "X-Request-ID"

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
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = rid
    return response


app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
