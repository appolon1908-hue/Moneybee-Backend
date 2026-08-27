# MoneyBee API request-path contract

This document defines the canonical request path for borrower, lender, administrator, and finance traffic. It is a binding implementation rule for the frontend API client, Keycloak clients, FastAPI routes, service functions, and PostgreSQL transactions.

## Canonical request envelope

Every authenticated portal request uses:

```http
Authorization: Bearer <portal-specific Keycloak access token>
X-Organization-ID: <active MoneyBee organization UUID>
X-Request-ID: <unique request UUID>
X-Correlation-ID: <workflow correlation ID>
```

Replay-sensitive commands also use:

```http
Idempotency-Key: <8–160 character stable key>
```

Versioned resource commands use `If-Match` where the endpoint contract declares it, or an explicit `expected_version` field until that endpoint is migrated.

The following are prohibited as alternate security contexts:

- organization or tenant identity in JSON request bodies;
- organization or tenant identity in query parameters;
- idempotency keys duplicated in JSON request bodies;
- frontend-supplied role, permission, membership, lender, borrower, or administrator labels;
- a custom header that claims which portal sent the request.

## Portal-specific Keycloak clients

The `azp` claim is the authoritative browser-portal identity. Each portal must obtain its own token from its own public Keycloak client:

```text
Borrower portal  → moneybee-borrower
Lender portal    → moneybee-lender
Admin portal     → moneybee-admin
```

The three configured client-ID sets must be nonempty and disjoint. The API rejects a valid lender token on borrower/admin routes, a valid borrower token on lender/admin/finance routes, and a valid admin token on borrower/lender routes.

All browser tokens may share the API audience `moneybee-api`; the token's authorized party remains portal-specific.

## Shared transport

The frontend `packages/api-client` transport owns:

1. access-token acquisition and one refresh-safe retry after `401`;
2. `Authorization`;
3. `X-Organization-ID` from the authenticated portal's active tenant selection;
4. request and correlation IDs;
5. `Idempotency-Key` for replay-sensitive commands;
6. `If-Match` for supported versioned resources;
7. normalized API errors.

Feature clients own paths, request/response types, and command-specific bodies. They may not independently invent authentication, tenant, or replay headers.

## Backend authentication and tenancy

For each protected request, `current_principal` performs this sequence:

1. validate JWT key ID, algorithm, signature, issuer, audience, expiry, issued-at, and not-before;
2. validate the token's `azp` or `client_id` against the requested route's portal boundary;
3. resolve the local identity only by immutable `issuer + subject`;
4. resolve `X-Organization-ID` against active organization memberships;
5. load local roles and permissions from PostgreSQL;
6. expose an immutable `Principal` to the route and service layer.

The backend never trusts an email address, frontend role label, query parameter, or JSON tenant value as an authorization decision.

## Borrower request path

Example: complete a borrower task.

```text
Borrower Vue screen
→ packages/api-client borrower client
→ PATCH /api/v2/borrower/tasks/{task_id}
→ borrower Keycloak token + X-Organization-ID + request/correlation IDs
→ current_principal
→ borrower route
→ task ownership and allowed-transition checks
→ PortalTask update + AuditEvent
→ one PostgreSQL commit
```

Relevant tables include:

```text
users
external_identities
organizations
organization_memberships
user_role_bindings
role_permissions
portal_tasks
portal_notifications
portal_conversations
portal_messages
document_upload_sessions
documents
audit_events
outbox_events
```

Borrower application and document access also validates application ownership through the resolved borrower organization before querying or mutating records.

## Lender request path

Example: record a lender decision.

```text
Lender Vue screen
→ packages/api-client lender client
→ GET /api/v2/lender/submissions/{id}/workspace to obtain current version
→ POST /api/v2/lender/submissions/{id}/decisions
→ lender Keycloak token + X-Organization-ID + Idempotency-Key
→ current_principal
→ lender organization scope
→ permission + submission ownership + expected-version checks
→ SELECT ... FOR UPDATE
→ LenderSubmission + UnderwritingReview + AuditEvent + OutboxEvent + IdempotencyRecord
→ one PostgreSQL commit
```

The canonical lender paths are:

```text
GET   /api/v2/lender/dashboard
GET   /api/v2/lender/programs
PATCH /api/v2/lender/programs/{program_id}
GET   /api/v2/lender/submissions/{submission_id}/workspace
GET   /api/v2/lender/bank-review-queue
GET   /api/v2/lender/submissions/{submission_id}/bank-transactions
POST  /api/v2/lender/submissions/{submission_id}/decisions
GET   /api/v2/lender/fundings
```

No singular `/decision`, `/bank-analysis-queue`, `/portfolio`, or unimplemented `/assignment` path is part of the contract.

## Administrator request path

Example: update an operations task.

```text
Admin Vue screen
→ packages/api-client admin client
→ PATCH /api/v2/admin/tasks/{task_id}
→ admin Keycloak token + X-Organization-ID + request/correlation IDs
→ current_principal
→ MoneyBee membership + explicit permission checks
→ SELECT ... FOR UPDATE
→ transition and assignment validation
→ PortalTask + AuditEvent
→ one PostgreSQL commit
```

Administrator catalog, operations, webhook-recovery, CRM-delivery, and finance routes use the same envelope and principal resolution.

## Finance request path

Example: post a journal entry.

```text
Admin/finance Vue screen
→ packages/api-client finance client
→ POST /api/v2/finance/journal-entries
→ admin Keycloak token
→ X-Organization-ID
→ X-Request-ID
→ X-Correlation-ID
→ Idempotency-Key
→ current_principal + admin portal-token boundary
→ finance.post permission
→ active tenant resolution
→ canonical request hash
→ existing-key/hash replay check
→ balanced journal and account/period validation
→ JournalEntry + JournalPosting[] + AuditEvent + OutboxEvent
→ one PostgreSQL commit
```

Finance tenant identity is never accepted in JSON or query parameters. `Idempotency-Key` is accepted only as a header.

The journal database enforces:

```text
UNIQUE (organization_id, entry_number)
UNIQUE (organization_id, idempotency_key)
NOT NULL request_hash
CHECK posting side
CHECK posting amount > 0
foreign keys to organization, period, account and linked business records
```

A repeated key with the same canonical request hash returns the original journal with:

```http
X-Idempotent-Replay: true
```

A repeated key with different economic data returns `409 IDEMPOTENCY_CONFLICT` and does not write partial rows.

## Transaction ownership

Routes parse transport concerns and call one service operation. A service that performs a command owns exactly one commit for the complete business operation.

A successful command must atomically persist its authoritative state and, where applicable:

- audit evidence;
- idempotency evidence;
- outbox evidence;
- optimistic-concurrency state.

A route must not commit one part of a business operation and ask a later adapter, worker, or request to complete correctness.

External delivery remains asynchronous:

```text
MoneyBee transaction
→ durable outbox
→ controlled worker
→ Codestra middleware
→ allowlisted provider/Odoo/Klyrow adapter
→ signed receipt
→ durable inbox/reconciliation evidence
```

The worker must remain disabled while `ENABLE_EXTERNAL_DELIVERY=false` or the approved provider configuration is unavailable.

## Database boundary

MoneyBee PostgreSQL is the system of record for lending and finance correctness. Codestra, Odoo, n8n, Klyrow, Keycloak, lenders, and provider adapters cannot connect to or write directly to it.

Keycloak owns passwords, MFA, federation, sessions, and recovery. MoneyBee stores only the local `issuer + subject` binding and authorization data; access tokens, refresh tokens, passwords, SMTP credentials, and provider secrets are prohibited from MoneyBee tables, audit details, and outbox payloads.

## Contract verification

CI must verify:

```text
frontend typecheck
frontend client-path tests
backend Ruff and compilation
backend PostgreSQL tests
Alembic upgrade/downgrade/re-upgrade
OpenAPI snapshot drift
portal token-boundary tests
tenant-isolation tests
idempotency collision tests
one-transaction finance evidence
Docker image builds and security scans
```

A successful build is not deployment authorization. Staging runtime paths, image digests, secrets, Keycloak clients, PostgreSQL backups, migrations, and rollback evidence remain separate gates.
