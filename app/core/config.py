from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VTP_DEV_BASE_URL = "https://partnerdev.viettelpost.vn"
VTP_PRODUCTION_BASE_URL = "https://partner.viettelpost.vn"


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "vip-shipping-gateway"
    # Commit the running image was built from (Dockerfile build-arg GIT_SHA); not secret.
    app_git_sha: str | None = None
    database_url: str = "sqlite:///./vip_shipping.db"
    # PostgreSQL connect timeout: a silent DB host must not hold readiness or requests for
    # the OS default (~75 s measured, verifier PR #16).
    db_connect_timeout_seconds: int = 5

    # Default is the documented DEVELOPMENT environment. Production must be chosen
    # explicitly (VTP_BASE_URL) so that no default configuration can reach it.
    # validate_default: APP_ENV=production with VTP_BASE_URL left out must fail, not use dev.
    vtp_base_url: str = Field(default=VTP_DEV_BASE_URL, validate_default=True)
    vtp_username: str | None = None
    vtp_password: str | None = None
    vtp_token: str | None = None
    vtp_timeout_seconds: float = 20.0

    webhook_shared_secret: str | None = None
    # IANA timezone of Viettel Post ORDER_STATUSDATE. The official webhook page does not
    # state it, so it is unset by default and event times stay unzoned (raw text kept).
    # Set only after Viettel Post confirms it, e.g. "Asia/Ho_Chi_Minh".
    vtp_webhook_timezone: str | None = None
    webhook_max_body_bytes: int = 64 * 1024

    # G12 security. Only SHA-256 digests of keys: "<id>:<sha256 hex>,..." (D-033).
    api_keys: str | None = None
    api_max_body_bytes: int = 256 * 1024

    # G11 observability / resilience
    log_level: str = "INFO"
    log_format: str = "text"  # "text" | "json"
    provider_retry_max_attempts: int = 3  # read-only provider calls only (D-031)
    provider_retry_base_delay: float = 0.2
    provider_retry_max_delay: float = 2.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        # A config error must never print other settings (tokens, passwords) into logs.
        hide_input_in_errors=True,
    )

    @field_validator("vtp_base_url")
    @classmethod
    def _vtp_endpoint_matches_environment(cls, value: str, info: ValidationInfo) -> str:
        """Credentials only ever go to an official Viettel Post host, and production and
        development cannot be crossed by a missing or stray variable (CR-READY-001).
        A field validator (not a model one) so an error never echoes other settings."""
        base = value.rstrip("/")
        if base not in (VTP_DEV_BASE_URL, VTP_PRODUCTION_BASE_URL):
            raise ValueError("VTP_BASE_URL must be the Viettel Post development or production URL")
        is_production = str(info.data.get("app_env", "")).strip().lower() == "production"
        if is_production and base != VTP_PRODUCTION_BASE_URL:
            raise ValueError("APP_ENV=production requires VTP_BASE_URL=" + VTP_PRODUCTION_BASE_URL)
        if base == VTP_PRODUCTION_BASE_URL and not is_production:
            raise ValueError("the production VTP_BASE_URL requires APP_ENV=production")
        return base


settings = Settings()
