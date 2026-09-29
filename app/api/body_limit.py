"""Hard request-body limit as a pure ASGI middleware (G12, verifier PR #18 finding 1).

Counts the bytes actually received, so ``Transfer-Encoding: chunked`` (no Content-Length)
cannot bypass it, and runs BEFORE routing/authentication, so unauthenticated callers
cannot make the server buffer large bodies. The body is read up to the limit, then
replayed to the application; memory per request is bounded by the limit.
"""

import json
from collections.abc import Callable

Limit = Callable[[str], int | None]


class BodyLimitMiddleware:
    def __init__(self, app, limit_for: Limit) -> None:
        self.app = app
        self.limit_for = limit_for

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit_for(scope.get("path", ""))
        if limit is None:
            return await self.app(scope, receive, send)

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            return await self._too_large(send)

        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return  # client went away; nothing to answer
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                return await self._too_large(send)
            chunks.append(body)
            more = message.get("more_body", False)

        buffered = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()  # later calls: wait for disconnect as usual

        return await self.app(scope, replay, send)

    @staticmethod
    async def _too_large(send) -> None:
        body = json.dumps(
            {"error": "payload_too_large", "detail": "request body too large"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"cache-control", b"no-store"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
