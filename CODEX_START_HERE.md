# MoneyBee Codex Start Here

This repository is governed by:

1. `docs/architecture/MONEYBEE_PRODUCTION_BLUEPRINT_V3.md`
2. `docs/codex/PR_DELIVERY_GOVERNANCE.md`
3. `docs/codex/MONEYBEE_12_STEP_IMPLEMENTATION.md`
4. The individual work-package specification for the current step.

These documents supersede earlier generic architecture or hardening documents where they conflict.

## Current Status

OVERALL_SYSTEM_STATUS = PARTIAL
FINAL_STATUS = PARTIAL

MoneyBee is not production-ready.

Do not infer production readiness from:

- CI success
- migrations passing
- provider credentials existing
- no failed outbox records
- configuration completeness
- an individual work package passing

## First Backend Work Package

Implement:

`auth/local-identity-tenancy`

Read:

`docs/codex/STEP_01B_BACKEND_IDENTITY_TENANCY.md`

Do not begin Step 2 until the paired frontend Keycloak PKCE PR and this backend identity PR are independently reviewable and have passed their required tests.

## Mandatory Rules

Do not auto-merge.

Do not deploy production.

Do not enable live financial capabilities.

Do not modify production data manually.

Do not use `Base.metadata.create_all()` as a production migration.

Do not rely on SQLite as proof of PostgreSQL transactional behavior.

Do not allow Odoo or n8n to write directly to MoneyBee PostgreSQL.

Do not route all external events through one generic CRM capability.

Do not automatically retry unsafe provider POST operations unless the provider supplies stable idempotency semantics.

## Final Authority

MoneyBee owns lending truth.

Odoo Community is a CRM projection.

Codestra is an integration/control plane.

n8n executes allowlisted workflows.

External providers integrate through adapters and durable events.

