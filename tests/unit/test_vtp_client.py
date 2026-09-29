import httpx
import pytest

from app.providers.viettel_post.client import TOKEN_HEADER, ViettelPostClient
from app.providers.viettel_post.errors import (
    ViettelPostAuthError,
    ViettelPostBusinessError,
    ViettelPostClientError,
    ViettelPostError,
    ViettelPostInvalidResponseError,
    ViettelPostNetworkError,
    ViettelPostServerError,
    ViettelPostTimeoutError,
    redact,
)
from tests.unit.vtp_fakes import (
    BASE_URL,
    FAKE_LONG_TOKEN,
    FAKE_PASSWORD,
    Recorder,
    make_client,
    ok,
    rejected,
    respond,
)

PATH = "/v2/order/getPrice"


def raising(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


@pytest.mark.asyncio
async def test_token_goes_in_token_header_not_authorization():
    recorder = Recorder({PATH: respond(ok({}))})
    client = make_client(recorder)

    await client.request_envelope("POST", PATH, token=FAKE_LONG_TOKEN, json={"A": 1})

    request = recorder.requests[0]
    assert request.url == httpx.URL(f"{BASE_URL}{PATH}")
    assert request.headers[TOKEN_HEADER] == FAKE_LONG_TOKEN
    assert "authorization" not in request.headers
    assert request.headers["Content-Type"] == "application/json;charset=UTF-8"


@pytest.mark.asyncio
async def test_no_token_header_without_token():
    recorder = Recorder({PATH: respond(ok({}))})
    await make_client(recorder).request("POST", PATH, json={})
    assert TOKEN_HEADER not in recorder.requests[0].headers


def test_base_url_and_timeout_are_configurable():
    client = ViettelPostClient(base_url="https://partnerdev.viettelpost.vn/", timeout=7.5)
    assert client.base_url == "https://partnerdev.viettelpost.vn"
    assert client.timeout == 7.5


@pytest.mark.asyncio
async def test_timeout_maps_to_timeout_error():
    client = make_client(raising(httpx.ReadTimeout("slow")))
    with pytest.raises(ViettelPostTimeoutError):
        await client.request("POST", PATH, token=FAKE_LONG_TOKEN)


@pytest.mark.asyncio
async def test_network_failure_maps_to_network_error():
    client = make_client(raising(httpx.ConnectError(f"refused {FAKE_LONG_TOKEN}")))
    with pytest.raises(ViettelPostNetworkError) as info:
        await client.request("POST", PATH, token=FAKE_LONG_TOKEN)
    assert FAKE_LONG_TOKEN not in str(info.value)


@pytest.mark.asyncio
async def test_http_4xx_maps_to_client_error():
    client = make_client(Recorder({PATH: respond(rejected("Bad request"), status_code=400)}))
    with pytest.raises(ViettelPostClientError) as info:
        await client.request("POST", PATH)
    assert info.value.status_code == 400
    assert not isinstance(info.value, ViettelPostServerError)


@pytest.mark.asyncio
async def test_http_5xx_maps_to_server_error():
    client = make_client(Recorder({PATH: lambda r: httpx.Response(502, text="<html>gw</html>")}))
    with pytest.raises(ViettelPostServerError) as info:
        await client.request("POST", PATH)
    assert info.value.status_code == 502


@pytest.mark.asyncio
async def test_invalid_json_maps_to_invalid_response():
    client = make_client(Recorder({PATH: lambda r: httpx.Response(200, text="not json {")}))
    with pytest.raises(ViettelPostInvalidResponseError):
        await client.request("POST", PATH)


@pytest.mark.asyncio
async def test_empty_body_maps_to_invalid_response():
    client = make_client(Recorder({PATH: lambda r: httpx.Response(200)}))
    with pytest.raises(ViettelPostInvalidResponseError):
        await client.request("POST", PATH)


@pytest.mark.asyncio
async def test_missing_envelope_maps_to_invalid_response():
    client = make_client(Recorder({PATH: respond({"foo": 1})}))
    with pytest.raises(ViettelPostInvalidResponseError):
        await client.request_envelope("POST", PATH)


@pytest.mark.asyncio
async def test_business_rejection_maps_to_business_error():
    message = "Price does not apply to this itinerary!"
    client = make_client(Recorder({PATH: respond(rejected(message))}))
    with pytest.raises(ViettelPostBusinessError) as info:
        await client.request_envelope("POST", PATH, token=FAKE_LONG_TOKEN)
    assert message in str(info.value)
    assert not isinstance(info.value, ViettelPostAuthError)
    assert info.value.provider_status == 200


@pytest.mark.asyncio
async def test_list_message_is_joined():
    client = make_client(Recorder({PATH: respond(rejected(["Invalid [SENDER_WARD]", "x"]))}))
    with pytest.raises(ViettelPostBusinessError, match=r"Invalid \[SENDER_WARD\]; x"):
        await client.request_envelope("POST", PATH)


@pytest.mark.parametrize(
    "message",
    ["Header Token is required", "Token invalid", "Token invalid or expired"],
)
@pytest.mark.asyncio
async def test_token_rejections_map_to_auth_error(message):
    client = make_client(Recorder({PATH: respond(rejected(message))}))
    with pytest.raises(ViettelPostAuthError):
        await client.request_envelope("POST", PATH, token=FAKE_LONG_TOKEN)


@pytest.mark.asyncio
async def test_secrets_are_masked_in_every_error_path():
    echo = f"echo {FAKE_LONG_TOKEN} {FAKE_PASSWORD}"
    for status_code in (200, 401, 500):
        client = make_client(Recorder({PATH: respond(rejected(echo), status_code=status_code)}))
        with pytest.raises(ViettelPostError) as info:
            await client.request_envelope(
                "POST", PATH, token=FAKE_LONG_TOKEN, secrets=[FAKE_PASSWORD]
            )
        text = str(info.value)
        assert FAKE_LONG_TOKEN not in text
        assert FAKE_PASSWORD not in text
        assert "***" in text


def test_redact_masks_unknown_jwt_and_truncates():
    text = redact("token eyJabc.eyJdef.ghi end" + "x" * 500)
    assert "eyJabc" not in text
    assert len(text) <= 203


@pytest.mark.asyncio
async def test_close_is_idempotent():
    client = make_client(Recorder({PATH: respond(ok({}))}))
    await client.request("POST", PATH)
    await client.close()
    await client.close()
