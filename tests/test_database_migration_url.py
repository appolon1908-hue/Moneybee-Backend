"""DATABASE_MIGRATION_URL lets migrations run as a role with DDL rights
(moneybee_migrator) while the running api/worker connect with DATABASE_URL
as a DML-only role (moneybee_app) that can never CREATE/ALTER/DROP
anything (see deploy/postgres/init-app-roles.sh, migrations/env.py). This
pins the fallback behavior migrations/env.py depends on: prefer the
migration URL when set, fall back to the regular one otherwise, so a
deployment that never configures role separation (local dev, most of this
test suite) keeps working exactly as before.
"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

from app.config import Settings


def test_database_migration_url_defaults_to_none():
    settings = Settings(database_url="sqlite+aiosqlite:///./x.db")
    assert settings.database_migration_url is None


def test_database_migration_url_is_read_from_its_own_env_var(monkeypatch):
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "postgresql+asyncpg://moneybee_migrator:pw@db/moneybee")
    settings = Settings(database_url="postgresql+asyncpg://moneybee_app:pw@db/moneybee")
    assert settings.database_migration_url == "postgresql+asyncpg://moneybee_migrator:pw@db/moneybee"
    assert settings.database_url == "postgresql+asyncpg://moneybee_app:pw@db/moneybee"


def test_migrations_env_prefers_the_migration_url_when_set():
    settings = Settings(
        database_url="postgresql+asyncpg://moneybee_app:pw@db/moneybee",
        database_migration_url="postgresql+asyncpg://moneybee_migrator:pw@db/moneybee",
    )
    resolved = settings.database_migration_url or settings.database_url
    assert resolved == "postgresql+asyncpg://moneybee_migrator:pw@db/moneybee"


def test_migrations_env_falls_back_to_database_url_when_unset():
    settings = Settings(database_url="postgresql+asyncpg://moneybee_app:pw@db/moneybee")
    resolved = settings.database_migration_url or settings.database_url
    assert resolved == "postgresql+asyncpg://moneybee_app:pw@db/moneybee"
