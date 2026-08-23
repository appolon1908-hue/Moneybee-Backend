from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "MoneyBeeLoans API"
    build_sha: str = "development"
    migration_head: str = "unknown"

    database_url: str = (
        "postgresql+asyncpg://moneybee:moneybee@localhost:5432/moneybee"
    )
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = (
        "http://localhost:5173,"
        "http://localhost:5174,"
        "http://localhost:5175,"
        "http://localhost:5176"
    )

    keycloak_issuer: str = "https://auth.codestra.co/realms/codestra"
    keycloak_audience: str = "moneybee-api"
    keycloak_jwks_url: str = (
        "https://auth.codestra.co/realms/codestra/"
        "protocol/openid-connect/certs"
    )

    credit_live_pull: bool = False
    lenders_live_submission: bool = False
    esign_live_send: bool = False
    funding_live_confirmation: bool = False
    payments_enabled: bool = False
    payouts_enabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            item.strip()
            for item in self.cors_origins.split(",")
            if item.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
