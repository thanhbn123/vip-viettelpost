from fastapi import FastAPI
from app.api.routes import router as api_router

app = FastAPI(
    title="VIP Shipping Gateway",
    version="0.1.0",
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
def health():
    return {"status": "ok"}
