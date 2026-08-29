import os
from pathlib import Path


# Pytest imports this file before collecting test modules. Use setdefault so
# workflow-provided PostgreSQL settings remain authoritative while local and
# generic CI runs do not initialize the application with APP_ENV=local.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")

# AUTO_CREATE_SCHEMA=true is intentional for the ephemeral SQLite test DB.
# Runtime defaults remain False so Alembic owns real environment schemas.
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")

# LOCAL_AUTH_BYPASS=true is intentional here: the test suite runs against a
# local SQLite database without a live Keycloak instance. The production default
# is False after security hardening, and this override must only live in test
# configuration.
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")
os.environ.setdefault("LOCAL_IDENTITY_ENFORCEMENT", "false")
os.environ.setdefault("CODESTRA_MIDDLEWARE_WEBHOOK_TOLERANCE_SECONDS", "60")
os.environ.setdefault("PROVIDER_WEBHOOK_TOLERANCE_SECONDS", "60")
os.environ.setdefault(
    "PROVIDER_WEBHOOK_ALLOWLIST_CSV",
    "lender,docusign,sendgrid,odoo,n8n,experian",
)


def _remove_local_sqlite_file(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return
    database_path = url.removeprefix(prefix)
    if database_path in {":memory:", ""}:
        return
    path = Path(database_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.name.startswith("test-moneybee") and path.suffix in {".db", ".sqlite"}:
        path.unlink(missing_ok=True)


_remove_local_sqlite_file(os.environ["DATABASE_URL"])
_remove_local_sqlite_file("sqlite+aiosqlite:///./test-moneybee-finance.db")
