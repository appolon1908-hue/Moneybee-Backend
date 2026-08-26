# MoneyBee Portal Feature Stack

Status: implementation review stack; not production deployed.

## Branch order

1. `feature/portal-foundation`
2. `feature/borrower-portal-api`
3. `feature/lender-bank-portal-api`
4. `feature/admin-operations-api`
5. `feature/provider-webhook-gateway`

Each pull request is stacked on the preceding branch. None targets `main` until the existing Step 0 and identity prerequisites are independently reviewed and merged.

## Portal boundaries

- The frontend uses only HTTPS `/api/v2` endpoints.
- The API resolves Keycloak identity to local MoneyBee identity and active organization context.
- Borrower, lender, and MoneyBee administrative access is enforced server-side.
- Odoo remains a CRM projection and never writes directly to MoneyBee PostgreSQL.
- n8n consumes allowlisted durable events and never becomes the lending system of record.

## Shared capabilities

The portal foundation adds tenant-scoped tasks, notifications, conversations, messages, and document upload sessions. Document objects are written under a private quarantine prefix with server-side encryption metadata. Completion verifies object size, SHA-256 metadata, and upload-session ownership before a document can enter the scanning pipeline.

## Safety gates

The following capabilities remain disabled unless separately approved and configured:

```text
credit.live_pull=false
lenders.live_submission=false
esign.live_send=false
funding.live=false
documents.secure_upload=false
```

A passing test suite, generated OpenAPI contract, provider credentials, or completed portal screen does not activate a live financial capability.

## Required review evidence

Every branch must provide:

- migration upgrade and downgrade/re-upgrade evidence when schema changes;
- PostgreSQL tenant-isolation tests for authoritative data paths;
- authorization tests for borrower, lender, and admin cross-role access;
- idempotency and optimistic-concurrency tests for mutating operations;
- webhook signature, replay, duplicate, and manual-requeue tests;
- frontend typecheck, unit-test, production-build, and API-contract evidence;
- confirmation that no branch was merged to `main` and no production deployment occurred.
