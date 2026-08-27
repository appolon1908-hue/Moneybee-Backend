import os


# Pytest imports this file before collecting test modules. Use setdefault so
# workflow-provided PostgreSQL settings remain authoritative while local and
# generic CI runs do not initialize the application with APP_ENV=local.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db")
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")
os.environ.setdefault("LOCAL_IDENTITY_ENFORCEMENT", "false")
