from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "vip-shipping-gateway"
    database_url: str = "sqlite:///./vip_shipping.db"

    vtp_base_url: str = "https://partner.viettelpost.vn"
    vtp_username: str | None = None
    vtp_password: str | None = None
    vtp_token: str | None = None

    webhook_shared_secret: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
