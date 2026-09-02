import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config


def migration_database_url() -> str:
    explicit = os.getenv("MIGRATION_DATABASE_URL")
    if explicit:
        return explicit
    if os.getenv("APP_ENV", "local") in {"staging", "production"}:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is required for staging/production Alembic operations"
        )
    return os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")


config.set_main_option("sqlalchemy.url", migration_database_url().replace("%", "%%"))

from app import (  # noqa: E402, F401
    compliance_models,
    financial_models,
    identity_models,
    integration_models,
    models,
    public_intake_models,
)
from app.portal import models as portal_models  # noqa: E402, F401
from app.db_base import Base  # noqa: E402

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Historical migrations created a UNIQUE constraint plus a separate lookup index,
# while SQLAlchemy represents ``unique=True, index=True`` as one unique index.
# These pairs are structurally equivalent for application invariants and are kept
# stable to avoid dropping/rebuilding production constraints merely for naming.
_EQUIVALENT_INDEXES = {
    "ix_affiliates_tracking_code",
    "ix_bank_provider_states_connection_id",
    "ix_businesses_application_id",
    "ix_capability_flags_key",
    "ix_commercial_financing_disclosures_offer_id",
    "ix_commissions_funding_id",
    "ix_communication_templates_code",
    "ix_financial_profiles_application_id",
    "ix_fundings_application_id",
    "ix_notification_preferences_subject",
    "ix_operational_exceptions_fingerprint",
    "ix_outbox_events_correlation_id",
    "ix_renewal_opportunities_original_funding_id",
    "ix_user_accounts_subject",
    "ix_users_last_login_at",
    "uq_users_email_lower",
}
_EQUIVALENT_UNIQUES = {
    "affiliates_tracking_code_key",
    "bank_provider_states_connection_id_key",
    "businesses_application_id_key",
    "capability_flags_key_key",
    "commissions_funding_id_key",
    "communication_templates_code_key",
    "credit_authorizations_application_id_authorization_version_key",
    "financial_profiles_application_id_key",
    "fundings_application_id_key",
    "notification_preferences_subject_key",
    "operational_exceptions_fingerprint_key",
    "renewal_opportunities_original_funding_id_key",
    "user_accounts_subject_key",
    "uq_commercial_financing_disclosure_offer",
    "uq_credit_authorization_version",
}
_COMPATIBILITY_COLUMNS = {("bank_provider_states", "access_token_ciphertext")}


def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "index" and name in _EQUIVALENT_INDEXES:
        return False
    if type_ == "unique_constraint" and name in _EQUIVALENT_UNIQUES:
        return False
    if (
        type_ == "column"
        and reflected
        and (getattr(getattr(object_, "table", None), "name", None), name)
        in _COMPATIBILITY_COLUMNS
    ):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_sync_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(run_sync_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
