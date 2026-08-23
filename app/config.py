from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "dev", "staging", "production"] = "local"
    database_url: str = "sqlite+aiosqlite:///./moneybee.db"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_schema: bool = True
    local_auth_bypass: bool = True
    cors_origins_csv: str = (
        "http://localhost:5173,http://localhost:5174,"
        "http://localhost:5175,http://localhost:5176"
    )
    oidc_issuer: str = "https://auth.codestra.co/realms/codestra"
    oidc_audience: str = "moneybee-api"
    oidc_jwks_url: str = (
        "https://auth.codestra.co/realms/codestra/protocol/openid-connect/certs"
    )
    codestra_middleware_base_url: str | None = None
    codestra_middleware_token_url: str | None = None
    codestra_middleware_client_id: str | None = None
    codestra_middleware_client_secret: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_csv.split(",") if item.strip()]

    @model_validator(mode="after")
    def secure_environment(self) -> "Settings":
        legacy = "auth.codestra.agency"
        if legacy in self.oidc_issuer or legacy in self.oidc_jwks_url:
            raise ValueError("Legacy identity host is forbidden")
        if self.app_env in {"staging", "production"}:
            if self.local_auth_bypass or self.auto_create_schema:
                raise ValueError("Local bypass/schema creation must be disabled")
            if not self.oidc_issuer.startswith("https://auth.codestra.co/"):
                raise ValueError("Canonical issuer must use auth.codestra.co")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
