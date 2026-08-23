from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://moneybee:moneybee@localhost:5432/moneybee"
    redis_url: str = "redis://localhost:6379/0"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    keycloak_issuer: str = "https://auth.codestra.co/realms/codestra"
    keycloak_audience: str = "moneybee-api"
    auth_required: bool = True
    webhook_shared_secret: str = ""
    enable_live_lender_submission: bool = False
    enable_live_funding_actions: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def production_safety(self) -> "Settings":
        canonical_issuer = "https://auth.codestra.co/realms/codestra"
        if self.keycloak_issuer.rstrip("/") != canonical_issuer:
            raise ValueError("Only the canonical Codestra identity issuer is permitted")
        if self.environment.lower() == "production":
            if not self.auth_required:
                raise ValueError("AUTH_REQUIRED must be true in production")
            if self.keycloak_issuer != "https://auth.codestra.co/realms/codestra":
                raise ValueError("Production must use canonical Codestra issuer")
            if self.webhook_shared_secret in {"", "change-me", "change-me-in-secret-store"}:
                raise ValueError("Production webhook secret must come from a secret store")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
