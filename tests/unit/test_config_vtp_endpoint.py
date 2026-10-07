"""CR-READY-001: VTP credentials only reach an official host, and APP_ENV ties the choice."""

import pytest
from pydantic import ValidationError

from app.core.config import VTP_DEV_BASE_URL, VTP_PRODUCTION_BASE_URL, Settings


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_default_is_development():
    assert make().vtp_base_url == VTP_DEV_BASE_URL


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_non_production_uses_dev(env):
    assert make(app_env=env, vtp_base_url=VTP_DEV_BASE_URL + "/").vtp_base_url == VTP_DEV_BASE_URL


def test_production_requires_and_accepts_production_url():
    s = make(app_env="production", vtp_base_url=VTP_PRODUCTION_BASE_URL)
    assert s.vtp_base_url == VTP_PRODUCTION_BASE_URL
    with pytest.raises(ValidationError, match="APP_ENV=production requires"):
        make(app_env="production")  # VTP_BASE_URL left out: must not silently use dev
    with pytest.raises(ValidationError, match="APP_ENV=production requires"):
        make(app_env="Production", vtp_base_url=VTP_DEV_BASE_URL)


@pytest.mark.parametrize("env", ["development", "staging", ""])
def test_production_url_refused_outside_production(env):
    with pytest.raises(ValidationError, match="requires APP_ENV=production"):
        make(app_env=env, vtp_base_url=VTP_PRODUCTION_BASE_URL)


@pytest.mark.parametrize(
    "url",
    [
        "https://vtp.example.test",
        "http://partnerdev.viettelpost.vn",
        "https://partnerdev.viettelpost.vn.evil.test",
        "https://partner.viettelpost.vn/v2",
    ],
)
def test_any_other_host_is_refused(url):
    with pytest.raises(ValidationError, match="must be the Viettel Post"):
        make(vtp_base_url=url)


def test_config_error_never_echoes_other_settings():
    """The traceback of a refused config goes to logs: no token/password may appear."""
    secret = "fake-test-token-value-not-real"
    with pytest.raises(ValidationError) as info:
        make(app_env="production", vtp_token=secret, vtp_password=secret)
    assert secret not in str(info.value)


def test_refused_url_with_embedded_credentials_is_not_echoed():
    """hide_input_in_errors: a refused VTP_BASE_URL may itself carry a secret."""
    with pytest.raises(ValidationError) as info:
        make(vtp_base_url="https://u:fakePw9@e.test")  # short: pydantic truncates long input
    assert "fakePw9" not in str(info.value)
