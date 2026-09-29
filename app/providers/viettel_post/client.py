import httpx
from app.core.config import settings

class ViettelPostClient:
    def __init__(self) -> None:
        self.base_url = settings.vtp_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=20.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, *, token: str | None = None, json: dict | None = None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = await self._client.request(
            method,
            f"{self.base_url}/{path.lstrip('/')}",
            headers=headers,
            json=json,
        )
        response.raise_for_status()
        return response.json()
