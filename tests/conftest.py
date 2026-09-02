import os
from pathlib import Path


# Pytest imports this file before collecting test modules. Use setdefault so
# workflow-provided PostgreSQL settings remain authoritative while local and
# generic CI runs do not initialize the application with APP_ENV=local.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")
os.environ.setdefault("LOCAL_IDENTITY_ENFORCEMENT", "false")
os.environ.setdefault(
    "FIELD_ENCRYPTION_KEYS_JSON",
    '{"1": "zJ8vQ3mK7pR2sT5wX9aB1cD4eF6gH0iJ2kL4mN6oP8q="}',
)
os.environ.setdefault("FIELD_ENCRYPTION_ACTIVE_KEY_VERSION", "1")


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
