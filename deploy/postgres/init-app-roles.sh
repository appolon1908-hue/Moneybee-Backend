#!/bin/bash
# Runs once, automatically, only against a brand-new Postgres data
# directory (docker-entrypoint-initdb.d/*.sh convention on the official
# postgres image) - never re-runs against an existing volume, so it never
# needs to be idempotent against already-existing roles.
#
# Creates two roles beneath the POSTGRES_USER bootstrap superuser so that
# neither ongoing application traffic nor even routine migrations run as
# that superuser day to day:
#   - moneybee_migrator: owns the database, can run DDL (Alembic). Used
#     only by the one-shot `migrate` service/profile.
#   - moneybee_app: DML only (SELECT/INSERT/UPDATE/DELETE + sequence
#     usage), no CREATE/ALTER/DROP anywhere. Used by the api/worker
#     services that actually process untrusted request input. Automatically
#     picks up grants on every table moneybee_migrator creates in the
#     future via ALTER DEFAULT PRIVILEGES - a migration never needs a
#     follow-up grants script.
#
# The bootstrap superuser (POSTGRES_USER) itself still exists after this
# runs - Postgres always needs one - but nothing in this repo's compose
# models points DATABASE_URL or DATABASE_MIGRATION_URL at it once
# MONEYBEE_MIGRATOR_PASSWORD_FILE/MONEYBEE_APP_PASSWORD_FILE are configured.
set -euo pipefail

: "${MONEYBEE_MIGRATOR_PASSWORD_FILE:?set MONEYBEE_MIGRATOR_PASSWORD_FILE}"
: "${MONEYBEE_APP_PASSWORD_FILE:?set MONEYBEE_APP_PASSWORD_FILE}"

migrator_password="$(cat "$MONEYBEE_MIGRATOR_PASSWORD_FILE")"
app_password="$(cat "$MONEYBEE_APP_PASSWORD_FILE")"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v migrator_password="'$migrator_password'" \
  -v app_password="'$app_password'" \
  <<-'SQL'
    CREATE ROLE moneybee_migrator WITH LOGIN PASSWORD :migrator_password;
    ALTER DATABASE moneybee OWNER TO moneybee_migrator;

    CREATE ROLE moneybee_app WITH LOGIN PASSWORD :app_password;
    GRANT CONNECT ON DATABASE moneybee TO moneybee_app;
    GRANT USAGE ON SCHEMA public TO moneybee_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO moneybee_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO moneybee_app;

    ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO moneybee_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE moneybee_migrator IN SCHEMA public
      GRANT USAGE, SELECT ON SEQUENCES TO moneybee_app;

    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
