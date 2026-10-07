"""Shared fakes for Viettel Post adapter tests. No real credential or network access."""

import json
from collections.abc import Callable

import httpx

from app.providers.viettel_post.auth import ViettelPostAuth
from app.providers.viettel_post.client import ViettelPostClient

BASE_URL = "https://vtp.test"
FAKE_USERNAME = "fake-user-0000"
FAKE_PASSWORD = "fake-pass-not-real"
FAKE_SHORT_TOKEN = "eyJfake.eyJshortterm.fakesig"
FAKE_LONG_TOKEN = "eyJfake.eyJlongterm.fakesig"


def ok(data, message="OK") -> dict:
    return {"status": 200, "error": False, "message": message, "data": data}


def rejected(message, status=200) -> dict:
    return {"status": status, "error": True, "message": message, "data": None}


class Recorder:
    """A MockTransport handler that records requests and answers from a route table."""

    def __init__(self, routes: dict[str, Callable[[httpx.Request], httpx.Response]]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(request.url.path)
        if handler is None:
            return httpx.Response(404, json=rejected("no route in test"))
        return handler(request)

    def bodies(self, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]


def respond(payload, status_code: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status_code, json=payload)


def make_client(handler) -> ViettelPostClient:
    return ViettelPostClient(base_url=BASE_URL, timeout=5.0, transport=httpx.MockTransport(handler))


def make_auth(client: ViettelPostClient, *, static_token: str = "") -> ViettelPostAuth:
    return ViettelPostAuth(
        client, username=FAKE_USERNAME, password=FAKE_PASSWORD, static_token=static_token
    )
