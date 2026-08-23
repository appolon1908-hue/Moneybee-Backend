from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"
    git_sha: str = "dev"
    migration_head: str = "0001_bootstrap"
    database_url: str = "postgresql+asyncpg://moneybee:moneybee@localhost:5432/moneybee"
    redis_url: str = "redis://localhost:6379/0"
    credit_live_pull: bool = False
    lenders_live_submission: bool = False
    esign_live_send: bool = False
    funding_live_confirmation: bool = False
    payments: bool = False
    payouts: bool = False

    def capabilities(self) -> dict[str, bool]:
        return {
            "credit.live_pull": self.credit_live_pull,
            "lenders.live_submission": self.lenders_live_submission,
            "esign.live_send": self.esign_live_send,
            "funding.live_confirmation": self.funding_live_confirmation,
            "payments": self.payments,
            "payouts": self.payouts,
        }


settings = Settings()
