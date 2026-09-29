from pydantic_settings import BaseSettings, SettingsConfigDict

VTP_DEV_BASE_URL = "https://partnerdev.viettelpost.vn"
VTP_PRODUCTION_BASE_URL = "https://partner.viettelpost.vn"


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "vip-shipping-gateway"
    database_url: str = "sqlite:///./vip_shipping.db"
    # PostgreSQL connect timeout: a silent DB host must not hold readiness or requests for
    # the OS default (~75 s measured, verifier PR #16).
    db_connect_timeout_seconds: int = 5

    # Default is the documented DEVELOPMENT environment. Production must be chosen
    # explicitly (VTP_BASE_URL) so that no default configuration can reach it.
    vtp_base_url: str = VTP_DEV_BASE_URL
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
