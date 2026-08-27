# CODEX MISSION — MONEYBEE CODE AND RELEASE READINESS ONLY

**Mission ID:** `MB-CODE-AND-RELEASE-READINESS-20260827`  
**Mission owner:** Ralph Appolon  
**Issued:** 2026-08-27  
**Execution mode:** repository-only, fail-closed, exact-SHA, evidence-driven  
**Staging-server update authorization:** **NOT GRANTED**  
**Production authorization:** **NOT GRANTED**

## Controlling statement

PR #11 and issue #18 define work and review requirements. They do not authorize a staging-server update, production change, SSH execution, workflow dispatch that contacts a host, server-side migration, container rollout, DNS/firewall/proxy change, secret injection, or activation of external services.

Codex is authorized to update repository branches, resolve code conflicts, align API contracts, run CI, prepare draft PRs, and produce non-secret release-readiness evidence. Codex must stop before any host contact or environment mutation.

```text
STAGING_SERVER_UPDATE_AUTHORIZED=NO
PRODUCTION_CHANGE_AUTHORIZED=NO
SSH_EXECUTION_AUTHORIZED=NO
READ_ONLY_PREFLIGHT_AUTHORIZED=NO
DEPLOYMENT_WORKFLOW_DISPATCH_AUTHORIZED=NO
SERVER_SIDE_MIGRATION_AUTHORIZED=NO
AUTO_MERGE_AUTHORIZED=NO
```

## Mission outcome

Produce clean, exact-SHA backend and frontend integration branches that combine the reviewed authentication, separate portal-token, portal-contract, finance-ledger, database, and split-Docker work. Make the complete automated validation matrix pass and prepare draft release artifacts and instructions for later human review.

The mission is complete when the repository evidence is ready for a future deployment decision. The mission is **not** complete by updating a server, and it may never report that a server was updated.

## Verified source state

### Backend

Repository: `appolon1908-hue/Moneybee-Backend`

```text
Account, identity, separate portal tokens and database branch:
feature/keycloak-account-lifecycle
fb2866b033811bcb1c5e2522dc23bd350866164b

Finance and normalized portal-contract branch:
feature/financial-system-foundation
07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3

Integration branch:
integration/staging-moneybee-20260827
expected starting SHA: fb2866b033811bcb1c5e2522dc23bd350866164b
```

### Frontend

Repository: `appolon1908-hue/Moneybee-frontend-`

```text
Portal contract, registration/recovery and separate-token branch:
feature/keycloak-account-lifecycle
b7b0abb17a3325ba04941b60d548897a9bf7e93d

Finance portal branch:
feature/financial-system-foundation
033e2190de4b9cf78f73c6d1a81f8668c5efef83

Integration branch:
integration/staging-moneybee-20260827
expected starting SHA: b7b0abb17a3325ba04941b60d548897a9bf7e93d
```

Frontend PR #18 is a separate enterprise design-system PR. Do not substitute it for the portal-contract and finance integration work.

## Permitted Git procedure

### Backend

1. Fetch all refs and verify the recorded SHAs still identify the reviewed commits.
2. Confirm `integration/staging-moneybee-20260827` starts from the recorded account-lifecycle SHA, or report the exact divergence before changing it.
3. Integrate exact finance head `07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3` using a normal reviewable merge or a documented equivalent that preserves ancestry.
4. Resolve genuine code conflicts only. Preserve:
   - borrower, lender and admin Keycloak client separation;
   - `azp` or `client_id` portal-token validation;
   - local `issuer + subject` identity binding;
   - active organization, membership, role and permission checks;
   - PostgreSQL migrations and a single Alembic head;
   - idempotency, optimistic concurrency, audit and outbox records;
   - finance double-entry and tenant isolation controls;
   - split backend API, worker and migration Docker ownership;
   - all external/live capability gates in the disabled state.
5. Regenerate OpenAPI only through the repository-supported process.
6. Commit the integration fixes to the integration branch and open or update a draft PR for review.

### Frontend

1. Fetch all refs and verify the recorded SHAs.
2. Confirm `integration/staging-moneybee-20260827` starts from the recorded account/portal-contract SHA, or report the exact divergence.
3. Integrate exact finance head `033e2190de4b9cf78f73c6d1a81f8668c5efef83` using a reviewable merge or documented equivalent.
4. Preserve:
   - distinct public clients `moneybee-borrower`, `moneybee-lender`, and `moneybee-admin`;
   - separate portal session/token storage;
   - Authorization Code + PKCE;
   - selected `X-Organization-ID` propagation;
   - request/correlation IDs;
   - idempotency and `If-Match` headers for controlled mutations;
   - canonical `/api/v2` borrower, lender, admin and finance routes;
   - the Alpine/OpenSSL runtime fix;
   - separate marketing, borrower, lender and admin images.
5. Remove duplicate or stale API clients instead of retaining parallel contracts.
6. Commit integration fixes and open or update a draft PR for review.

Do not force-push either integration branch.

## Canonical request path to prove in tests

```text
Vue portal
→ typed API client
→ portal-specific Keycloak client/session
→ Authorization: Bearer <portal-specific token>
→ X-Organization-ID
→ X-Request-ID
→ X-Correlation-ID
→ Idempotency-Key for replay-sensitive mutations
→ If-Match for version-controlled writes
→ FastAPI /api/v2 route
→ JWT issuer/audience/signature/expiry validation
→ portal-client validation from azp or client_id
→ local issuer + subject resolution
→ active organization, membership, permission and resource checks
→ service/domain command or query
→ one SQLAlchemy/PostgreSQL transaction
→ authoritative rows, idempotency evidence, audit event and outbox event
→ commit
→ typed OpenAPI response
→ frontend state
```

A borrower token must fail on lender/admin-only routes. A lender token must fail on borrower/admin-only routes. An admin token must not become a borrower or lender token merely because the user has another membership.

## Canonical route alignment

At minimum, confirm and test these contracts:

```text
GET  /api/v2/borrower/workspace
GET  /api/v2/lender/workspace
GET  /api/v2/admin/workspace
GET  /api/v2/lender/bank-review-queue
GET  /api/v2/lender/portfolio
POST /api/v2/lender/submissions/{submission_id}/decisions

GET  /api/v2/finance/accounts
POST /api/v2/finance/accounts
GET  /api/v2/finance/periods
POST /api/v2/finance/periods
POST /api/v2/finance/periods/{period_id}/close
GET  /api/v2/finance/journal-entries
POST /api/v2/finance/journal-entries
GET  /api/v2/finance/journal-entries/{entry_id}/postings
GET  /api/v2/finance/trial-balance
```

Do not reintroduce these legacy or conflicting transport paths:

```text
/api/v2/portal/tasks
/api/v2/portal/notifications
/api/v2/portal/conversations
/api/v2/lender/bank-analysis-queue
/api/v2/lender/submissions/{submission_id}/decision
```

## Backend validation gates

```text
PYTHON_COMPILE=PASS
RUFF=PASS
PYTEST=PASS
POSTGRES_INTEGRATION=PASS
IDENTITY_TENANCY=PASS
PORTAL_TOKEN_SEPARATION=PASS
PORTAL_CONTRACT_VALIDATION=PASS
FINANCE_LEDGER_TESTS=PASS
TENANT_ISOLATION=PASS
IDEMPOTENCY=PASS
CONCURRENCY=PASS
OPENAPI_DRIFT=PASS
ALEMBIC_SINGLE_HEAD=PASS
MIGRATION_EMPTY_TO_HEAD=PASS
MIGRATION_BASELINE_TO_HEAD=PASS
MIGRATION_DOWNGRADE_UPGRADE=PASS
BACKEND_API_IMAGE_BUILD=PASS
BACKEND_WORKER_IMAGE_BUILD=PASS
BACKEND_MIGRATE_IMAGE_BUILD=PASS
VULNERABILITY_GATE=PASS
```

PostgreSQL—not SQLite—must supply the migration and transaction evidence used for readiness.

## Frontend validation gates

```text
PNPM_FROZEN_INSTALL=PASS
CONTRACTS_CHECK=PASS
TYPESCRIPT=PASS
VITEST=PASS
PORTAL_TOKEN_CONFIGURATION=PASS
BORROWER_BUILD=PASS
LENDER_BUILD=PASS
ADMIN_BUILD=PASS
MARKETING_BUILD=PASS
BORROWER_IMAGE_BUILD=PASS
LENDER_IMAGE_BUILD=PASS
ADMIN_IMAGE_BUILD=PASS
MARKETING_IMAGE_BUILD=PASS
VULNERABILITY_GATE=PASS
```

## Release-readiness preparation allowed

Codex may prepare, without applying:

- draft `release/staging` PR descriptions;
- proposed branch-protection requirements;
- exact-SHA image build plans;
- digest-only Compose and release-lock templates;
- SBOM, provenance, signing and vulnerability evidence plans;
- migration, backup, restore and rollback procedures;
- runtime-path questions for `49.12.145.107`;
- a review-only readiness packet that contains no credentials and performs no remote action.

Codex must not create a protected release branch, merge into it, publish an approved release, or dispatch any release/deployment workflow without a separate explicit approval.

## Host boundary

Candidate host information may be documented as:

```text
49.12.145.107
```

But this mission does not authorize even a read-only SSH connection. Do not dispatch `runtime-path-preflight-read-only` and do not invoke `ops/runtime-path-preflight.sh` remotely.

A later approval must state:

```text
READ_ONLY_PREFLIGHT_AUTHORIZED=YES
TARGET_HOST=49.12.145.107
APPROVED_SSH_USER=<user>
APPROVED_KNOWN_HOSTS_EVIDENCE=<reference>
```

A separate later approval is required again for any staging mutation.

## Explicitly prohibited actions

Codex must not:

- SSH to or contact `49.12.145.107`;
- dispatch a workflow that contacts a server;
- create or modify remote directories, files, permissions, users or services;
- run server-side migrations or database commands;
- pull, start, stop, restart or replace remote containers;
- change DNS, Caddy, Nginx, Kong, firewall or TLS configuration;
- configure Keycloak, Google OAuth, Klyrow/Postal SMTP, Codestra middleware, Odoo or n8n;
- use or reveal Postal DKIM private keys; previously exposed keys remain designated compromised and require separate rotation work;
- inject or rotate secrets;
- enable external delivery, live email, live SMS, credit, lender submission, e-sign, funding, payment or payout capabilities;
- auto-merge or bypass independent review;
- report a staging or production deployment.

## Capability freeze

```text
ENABLE_EXTERNAL_DELIVERY=false
MIDDLEWARE_PROVIDER=disabled
LIVE_WRITES=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false
CREDIT_LIVE_PULL=false
LENDERS_LIVE_SUBMISSION=false
ESIGN_LIVE_SEND=false
FUNDING_LIVE_CONFIRMATION=false
PAYMENTS_ENABLED=false
PAYOUTS_ENABLED=false
COMMUNICATIONS_LIVE_EMAIL=false
COMMUNICATIONS_LIVE_SMS=false
```

## Stop conditions

Return `GO_NO_GO=NO_GO` and stop when:

- a recorded source SHA cannot be verified;
- integration requires dropping a security or database safeguard;
- exact-head CI fails and cannot be safely repaired within the focused branches;
- multiple Alembic heads remain;
- PostgreSQL migration or transaction tests fail;
- frontend contracts do not match reviewed OpenAPI;
- a portal token can access another portal's restricted routes;
- images fail vulnerability policy;
- a required action would contact or mutate a server;
- a required merge, release publication, preflight or deployment lacks separate explicit approval.

## Required final Codex report

```text
MISSION_ID=MB-CODE-AND-RELEASE-READINESS-20260827
BACKEND_START_SHA=fb2866b033811bcb1c5e2522dc23bd350866164b
BACKEND_FINANCE_SOURCE_SHA=07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3
BACKEND_INTEGRATION_SHA=<sha or BLOCKED>
FRONTEND_START_SHA=b7b0abb17a3325ba04941b60d548897a9bf7e93d
FRONTEND_FINANCE_SOURCE_SHA=033e2190de4b9cf78f73c6d1a81f8668c5efef83
FRONTEND_INTEGRATION_SHA=<sha or BLOCKED>
BACKEND_EXACT_HEAD_CI=<PASS|FAIL|PENDING>
FRONTEND_EXACT_HEAD_CI=<PASS|FAIL|PENDING>
PORTAL_TOKEN_SEPARATION=<PASS|FAIL>
API_CONTRACT_ALIGNMENT=<PASS|FAIL>
POSTGRES_MIGRATION_CYCLE=<PASS|FAIL>
FINANCE_LEDGER_TESTS=<PASS|FAIL>
FRONTEND_IMAGE_SECURITY=<PASS|FAIL>
DRAFT_BACKEND_PR=<url or NOT_CREATED>
DRAFT_FRONTEND_PR=<url or NOT_CREATED>
RELEASE_PLAN_READY=<YES|NO>
READ_ONLY_PREFLIGHT_RUN=NOT_AUTHORIZED
DEPLOYMENT_RUN=NOT_AUTHORIZED
SERVER_UPDATED=NO
STAGING_DEPLOYED=NO
PRODUCTION_CHANGED=NO
GO_NO_GO=NO_GO
BLOCKERS=<exact blockers or NONE_FOR_CODE_READINESS>
```

No value in this report may imply deployment authority. A future server update requires a separate approval with exact protected merged SHAs, immutable image digests, reviewed runtime paths, backup/restore evidence, maintenance window, authorized operator/executor, and the literal statement `STAGING_DEPLOYMENT_AUTHORIZED=YES`.
