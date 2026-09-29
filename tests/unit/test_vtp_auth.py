import pytest

from app.providers.viettel_post.auth import (
    LOGIN_PATH,
    LOGIN_VTP_PATH,
    OWNER_CONNECT_PATH,
    ViettelPostAuth,
    ViettelPostAuthResult,
)
from app.providers.viettel_post.errors import (
    ViettelPostAuthError,
    ViettelPostBusinessError,
    ViettelPostInvalidResponseError,
)
from tests.unit.vtp_fakes import (
    FAKE_LONG_TOKEN,
    FAKE_PASSWORD,
    FAKE_SHORT_TOKEN,
    FAKE_USERNAME,
    Recorder,
    make_auth,
    make_client,
    ok,
    rejected,
    respond,
)


def login_ok():
    return respond(ok({"userId": 1, "token": FAKE_SHORT_TOKEN, "partner": 1, "expired": 0}))


def owner_ok():
    return respond(ok({"userId": 1, "token": FAKE_LONG_TOKEN, "partner": 1, "expired": 0}))


@pytest.mark.asyncio
async def test_auth_success_runs_login_then_ownerconnect():
    recorder = Recorder({LOGIN_PATH: login_ok(), OWNER_CONNECT_PATH: owner_ok()})
    auth = make_auth(make_client(recorder))

    result = await auth.authenticate()

    assert result.token == FAKE_LONG_TOKEN
    assert result.long_term is True
    assert result.provider_expired_field == 0
    assert [r.url.path for r in recorder.requests] == [LOGIN_PATH, OWNER_CONNECT_PATH]
    expected_body = {"USERNAME": FAKE_USERNAME, "PASSWORD": FAKE_PASSWORD}
    assert recorder.bodies(LOGIN_PATH) == [expected_body]
    assert recorder.bodies(OWNER_CONNECT_PATH) == [expected_body]
    # Login is anonymous; ownerconnect carries the short-term token in the "Token" header.
    assert "Token" not in recorder.requests[0].headers
    assert recorder.requests[1].headers["Token"] == FAKE_SHORT_TOKEN
    assert all(r.method == "POST" for r in recorder.requests)


@pytest.mark.asyncio
async def test_token_is_cached_until_invalidated():
    recorder = Recorder({LOGIN_PATH: login_ok(), OWNER_CONNECT_PATH: owner_ok()})
    auth = make_auth(make_client(recorder))

    await auth.get_token()
    await auth.get_token()
    assert len(recorder.requests) == 2

    auth.invalidate()
    await auth.get_token()
    assert len(recorder.requests) == 4


@pytest.mark.asyncio
async def test_static_token_skips_login():
    recorder = Recorder({})
    auth = make_auth(make_client(recorder), static_token=FAKE_LONG_TOKEN)

    assert await auth.get_token() == FAKE_LONG_TOKEN
    assert recorder.requests == []
    assert auth.can_refresh is False


@pytest.mark.asyncio
async def test_auth_rejection_raises_auth_error_without_secrets():
    recorder = Recorder({LOGIN_PATH: respond(rejected("Invalid owner account or password!"))})
    auth = make_auth(make_client(recorder))

    with pytest.raises(ViettelPostAuthError) as info:
        await auth.authenticate()

    text = str(info.value)
    assert "Invalid owner account or password!" in text
    assert FAKE_USERNAME not in text
    assert FAKE_PASSWORD not in text


@pytest.mark.asyncio
async def test_missing_token_field_is_invalid_response():
    recorder = Recorder({LOGIN_PATH: respond(ok({"userId": 1, "partner": 1}))})
    auth = make_auth(make_client(recorder))

    with pytest.raises(ViettelPostInvalidResponseError, match="data.token"):
        await auth.authenticate()


@pytest.mark.asyncio
async def test_null_data_is_invalid_response():
    recorder = Recorder({LOGIN_PATH: respond(ok(None))})
    auth = make_auth(make_client(recorder))

    with pytest.raises(ViettelPostInvalidResponseError):
        await auth.authenticate()


@pytest.mark.asyncio
async def test_missing_credentials_raise_without_network():
    recorder = Recorder({})
    client = make_client(recorder)
    auth = ViettelPostAuth(client, username="", password="", static_token="")
    with pytest.raises(ViettelPostAuthError, match="not configured"):
        await auth.authenticate()
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_login_vtp_exchanges_secret_token():
    secret = "FAKE-VTP-SECRET-0001"
    recorder = Recorder({LOGIN_VTP_PATH: respond(ok({"userId": 1, "token": FAKE_SHORT_TOKEN}))})
    auth = make_auth(make_client(recorder))

    result = await auth.login_vtp(secret)

    assert result.token == FAKE_SHORT_TOKEN
    assert recorder.bodies(LOGIN_VTP_PATH) == [{"token": secret}]


@pytest.mark.asyncio
async def test_login_vtp_rejection_masks_secret_token():
    secret = "FAKE-VTP-SECRET-0001"
    recorder = Recorder({LOGIN_VTP_PATH: respond(rejected(f"bad token {secret}"))})
    auth = make_auth(make_client(recorder))

    with pytest.raises(ViettelPostBusinessError) as info:
        await auth.login_vtp(secret)
    assert secret not in str(info.value)


def test_auth_result_repr_hides_token():
    result = ViettelPostAuthResult(token=FAKE_LONG_TOKEN, user_id=1)
    assert FAKE_LONG_TOKEN not in repr(result)


def test_auth_repr_hides_credentials():
    auth = make_auth(make_client(Recorder({})), static_token=FAKE_LONG_TOKEN)
    text = repr(auth)
    assert FAKE_USERNAME not in text
    assert FAKE_PASSWORD not in text
    assert FAKE_LONG_TOKEN not in text
