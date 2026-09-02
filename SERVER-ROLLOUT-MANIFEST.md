# MoneyBee server rollout contract

This document is input to a separate server mission. It does not authorize deployment.

- Base commit: `df1ef59550e7e9b25222a66bf34acd5f26398dc3`
- Target: protected head of `production-hardening-20260902` after exact-head CI
- Expected Alembic head: `20260901_0026`
- Runtime env: `MONEYBEE_BACKEND_ENV_FILE`, mode 0600, API/worker only
- Migration env: `MONEYBEE_MIGRATION_ENV_FILE`, mode 0600, migrate job only
- New runtime values: `DATABASE_RUNTIME_ROLE`, `RATE_LIMIT_BACKEND`, `TRUST_FORWARDED_FOR`, `TRUSTED_PROXY_CIDRS_CSV`, `REDIS_REQUIRED_FOR_READINESS`, recovery and architecture evidence statuses
- New secrets: runtime/migrator PostgreSQL passwords, `FIELD_ENCRYPTION_KEYS_JSON`, `FIELD_ENCRYPTION_CURRENT_VERSION`, `PII_LOOKUP_HMAC_KEY`; values remain outside Git
- PostgreSQL roles: reconcile `moneybee_admin`, `moneybee_migrator`, `moneybee_runtime`; run reviewed `ops/postgres` assets only after backup/rehearsal
- Backfill: no production backfill is authorized until PII expand/backfill migrations and validation tooling are complete
- Migration: one-shot `alembic upgrade head` with `MIGRATION_DATABASE_URL`
- Images: immutable API, worker and migrate digests built from the protected target SHA with SBOM/provenance
- Redis: persistent volume, ACL, AOF enabled, `appendfsync everysec`
- Readiness: PostgreSQL connectivity/current role/role attributes/migration head plus required Redis PING
- Rollback compatibility: retain prior images, encryption keys and compatibility columns; do not contract PII columns in the first rollout
- Rollback limitations: a forward-only data/state transition or external provider effect requires reconciliation, not blind image rollback

External capabilities stay disabled through initial read-only canary.
