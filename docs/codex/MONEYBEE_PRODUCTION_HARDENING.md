# MoneyBee Production Hardening
## Codex Implementation Specification

Status: APPROVED
Current readiness: PARTIAL


# PR DELIVERY AND RELEASE GOVERNANCE

Every implementation step in this specification MUST be delivered as a separate, independently reviewable pull request.

No step may be bundled into a large multi-phase PR unless explicitly approved.

Each PR must contain all applicable parts of the following delivery contract.

## Required PR Contents

1. Implementation
2. Additive database migration
3. Rollback / downgrade plan
4. Unit tests
5. PostgreSQL integration tests where applicable
6. Security / authorization tests
7. Concurrency tests where applicable
8. OpenAPI contract changes
9. Operational documentation
10. Deployment / rollback notes
11. Readiness evidence
12. Known limitations and blockers

A PR is not considered complete because code compiles or CI is green.

CI-green means only that the PR passed its current automated checks.

It does NOT mean:

- approved for merge
- approved for deployment
- production-ready
- provider-certified
- capability-enabled
- safe for live lending
- safe for live funding

---

## Capability Freeze

During all implementation PRs, the following live capabilities MUST remain disabled:

```text
credit.live_pull = false
lenders.live_submission = false
esign.live_send = false
funding.live_confirmation = false
payments = false
payouts = false
```

No implementation PR may automatically enable one of these capabilities.

No migration may seed them enabled.

No deployment script may enable them.

No UI control may silently enable them.

No readiness check may infer them enabled because credentials exist.

Capability activation is a separate production-governance action after launch certification.

---

## Merge Policy

Codex MUST NOT automatically merge any PR.

Each PR must be left in a reviewable state.

Required workflow:

```text
implementation
→ tests
→ CI
→ review evidence
→ human review
→ explicit merge approval
```

Codex may open or update a draft PR.

Codex must not:

- auto-merge
- force-push over reviewed work
- bypass required checks
- bypass branch protection
- deploy because CI passed

---

## Deployment Policy

No individual PR should automatically deploy to production.

A PR may deploy to staging only if the repository's approved CI/CD process explicitly supports staging deployment for that work package.

Production deployment is permitted only after the complete launch gate has passed.

---

## Readiness Policy

The MoneyBee system readiness endpoint/report MUST remain:

```text
FINAL_STATUS = PARTIAL
```

or:

```text
FINAL_STATUS = BLOCKED
```

until:

1. All implementation steps through Step 12 are complete.
2. Every mandatory launch gate has passed.
3. Production evidence exists for every required gate.
4. Dangerous capabilities have separate explicit approval.

No intermediate PR may set:

```text
FINAL_STATUS = READY
```

even if that PR itself is fully implemented and CI-green.

---

## Readiness Evidence Per PR

Each PR must provide machine-readable readiness evidence such as:

```json
{
  "work_package": "integration/durable-inbox",
  "status": "PASS",
  "source_sha": "...",
  "migration_head": "...",
  "unit_tests": "PASS",
  "postgres_tests": "PASS",
  "security_tests": "PASS",
  "concurrency_tests": "NOT_APPLICABLE",
  "openapi_status": "PASS",
  "rollback_documented": true,
  "staging_verified": false,
  "production_enabled": false,
  "blockers": []
}
```

This PR-level status does NOT change overall system readiness to READY.

---

## Migration Policy

Every schema-changing PR must use additive migration practices.

Preferred:

```text
expand
→ compatible application deployment
→ backfill
→ validate
→ contract
```

Each migration PR must include:

- migration file
- expected current migration head
- expected new migration head
- upgrade test
- downgrade / rollback strategy
- PostgreSQL migration test
- compatibility statement

Do not use `Base.metadata.create_all` as a production migration.

Do not manually modify the production database.

---

## Rollback Requirement

Every PR must describe its rollback behavior.

At minimum document:

- code rollback
- schema compatibility
- configuration rollback
- worker rollback
- provider impact
- data backfill impact
- whether downgrade migration is safe
- whether forward-fix is preferred

If a migration cannot safely be reversed, state this explicitly and provide a forward-fix strategy.

---

## OpenAPI Requirement

Any API-changing PR must:

1. Update request/response schemas.
2. Regenerate OpenAPI.
3. Add or update endpoint tests.
4. Validate compatibility with existing clients.
5. Document new error codes.
6. Document Idempotency-Key requirements.
7. Document If-Match requirements.
8. Document permissions.
9. Document ownership/tenant rules.
10. Document emitted events.

OpenAPI contract drift must fail CI.

---

## Security Requirement

Any PR involving authentication, authorization, PII, tenancy, lenders, contracts, funding, webhooks, documents, or operations MUST contain negative security tests.

Examples:

- wrong tenant rejected
- wrong borrower rejected
- wrong lender rejected
- missing permission rejected
- disabled user rejected
- disabled capability rejected
- stale version rejected
- duplicate action produces one result
- duplicate webhook produces one effect
- restricted PII not exposed

---

## PostgreSQL Test Requirement

Any PR relying on:

- transactions
- row locks
- concurrency
- unique constraints
- `SKIP LOCKED`
- JSONB
- PostgreSQL-specific indexes
- partial indexes
- advisory locks
- isolation semantics

must include tests against PostgreSQL.

SQLite-only tests are not sufficient.

---

## Operational Documentation Requirement

Every PR must add or update operational documentation covering:

- purpose
- normal operation
- health signal
- metrics
- alerts
- failure modes
- retry behavior
- manual recovery
- rollback
- ownership
- permissions required for recovery actions

Operators must not need direct database editing for normal recovery.

---

## Final Rule

A PR being CI-green is evidence that the PR passed its checks.

It is not authority to:

- merge
- deploy
- activate capabilities
- change readiness to READY
- allow real funding

Only the complete production launch process can do that.

---

# 12-STEP HARDENING PR SEQUENCE

| Step | PR / work package | Main deliverable |
|---:|---|---|
| 1 | `auth/local-identity-tenancy` | Keycloak frontend PKCE/session plus backend identity binding, users, organizations, memberships, and tenant isolation |
| 2 | `commands/command-context` | Command architecture and shared mutation context |
| 3 | `concurrency/versioning` | `If-Match`, row locks, version checks, and race tests |
| 4 | `integration/outbox-deliveries` | Destination subscriptions and per-destination delivery state |
| 5 | `integration/durable-inbox` | Inbox persistence, leasing, and asynchronous processing |
| 6 | `webhooks/provider-translators` | Codestra, Odoo, Middesk, Plaid, lender, DocuSign, and communications callbacks |
| 7 | `documents/secure-pipeline` | Presigned uploads, completion, ClamAV, quarantine, and download controls |
| 8 | `pii/security-controls` | Masking, reason-based reveal, reveal audit, and key versions |
| 9 | `lenders-contracts-funding` | Lender sends, contract state, funding dual control, and reconciliation |
| 10 | `operations/api-consistency` | Recovery APIs, stable errors, cursor pagination, rate limits, and payload policies |
| 11 | `observability/postgres-tests` | OpenTelemetry, metrics, alerts, and real PostgreSQL concurrency/security tests |
| 12 | `staging-recovery-release` | Staging, PITR, restore rehearsal, immutable images, SBOM, provenance, and canary |

When a work package changes both repositories, it MUST be delivered as one independently reviewable PR per repository under the same step. Step 1 therefore requires a frontend PKCE/session PR and a backend local-identity/tenancy PR. Neither PR may be merged automatically.

The execution order in this table overrides earlier work-package numbering while preserving every mandatory requirement in the underlying specifications.

Tests must accompany every implementation PR. Step 11 is the comprehensive PostgreSQL and observability certification work package, not the first point at which tests are written.

# OVERALL READINESS FLOW

```text
Steps 1–11 complete
        ↓
FINAL_STATUS remains PARTIAL

Step 12 complete
        ↓
run complete launch gate

launch gate partially passes
        ↓
PARTIAL / BLOCKED

all mandatory gates pass
        ↓
eligible for explicit READY review

human approval
        ↓
separate capability activation
```

Every PR completion report MUST include:

```text
OVERALL_SYSTEM_STATUS = PARTIAL
```

This value remains `PARTIAL` until Step 12 and the entire launch gate are complete. A work-package-level `PASS` must never be reported as overall system `READY`.



---

MoneyBee is not production-ready until every mandatory gate in this document is green.

Do not change the authority model:

MoneyBee = authoritative lending system

Codestra = integration/control plane

Odoo Community = CRM projection

n8n = approved workflow automation only

External providers must never write directly to MoneyBee PostgreSQL.

---

# WORK PACKAGE 1
## auth/local-identity-tenancy

Implement first.

### Goal

Bind every authenticated Keycloak identity to a local MoneyBee identity.

Identity key:

issuer + subject

Never use email as identity authority.

### Required tables

user_accounts

organizations

organization_memberships

roles

permissions

role_permissions

user_role_bindings

external_identities

### external_identities

Fields:

id
issuer
subject
user_id
created_at
last_seen_at

Unique:

issuer + subject

### organization_memberships

Fields:

organization_id
user_id
membership_type
active
created_at

Membership types may include:

BORROWER
LENDER
MONEYBEE_STAFF
AFFILIATE

### Principal

Create one authoritative Principal:

Principal
- user_id
- issuer
- subject
- organization_ids
- active_organization_id
- roles
- permissions
- lender_id
- borrower_id
- is_active

### Reject

disabled local user
missing identity binding
invalid tenant
inactive membership
cross-organization access

### Required tests

wrong issuer rejected
wrong audience rejected
expired token rejected
unknown identity rejected
disabled identity rejected
Borrower A cannot access Borrower B
Lender A cannot access Lender B
staff permission boundaries work

---

# WORK PACKAGE 2
## commands/command-context

Create one command model for every high-value mutation.

### CommandContext

actor
principal
organization_id
request_id
correlation_id
causation_id
idempotency_key
expected_version
ip_address
user_agent

### Required commands

SubmitApplication

RunFraudAssessment

StartMatching

CreateLenderSubmission

SendLenderSubmission

RetryLenderSubmission

SubmitCondition

DecideCondition

AcceptOffer

CreateContract

SendContract

ApproveFunding

SendFunds

ConfirmFunding

ReconcileFunding

RecordCommissionReceipt

AdjustCommission

RetryIntegration

ReplayIntegration

### Router rule

Routers may only:

authenticate
parse DTO
construct command/context
call service
return response

No domain state mutation in routers.

---

# WORK PACKAGE 3
## concurrency/versioning

Offer acceptance already has partial version protection.

Extend optimistic concurrency to:

application submission
conditions
lender submissions
contracts
funding
commissions

### Required header

If-Match: <aggregate-version>

### Behavior

missing If-Match on protected production mutation
→ 428 PRECONDITION_REQUIRED

stale version
→ 409 CONCURRENT_MODIFICATION

same logical action replay
→ idempotency result

### Database behavior

Use row locking where needed:

SELECT ... FOR UPDATE

Use version increment atomically.

### Required concurrency tests

two application submits

two different offer accepts

condition approve + reject race

contract send twice

funding approve twice

funds sent twice

funding confirm twice

commission receipt race

All tests must run against PostgreSQL.

SQLite is not accepted as concurrency proof.

---

# WORK PACKAGE 4
## integration/outbox-deliveries

Current design must stop routing every outbox event through one global Codestra path/capability.

### Add

event_subscriptions

outbox_deliveries

### event_subscriptions

event_type
destination
provider_connection_id
enabled
capability_key
schema_version
filter_json

Example:

offer.accepted.v1
→ codestra

funding.confirmed.v1
→ codestra

application.updated.v1
→ odoo projection

CommunicationQueued
→ notification worker

### outbox_deliveries

event_id
subscription_id
destination
status
attempts
locked_by
locked_until
next_attempt_at
first_attempt_at
last_attempt_at
delivered_at
last_http_status
last_error_code
last_error_message

States:

PENDING_CONFIGURATION
PENDING
PROCESSING
RETRYABLE
DELIVERED
FAILED_TERMINAL

### Capability change

Do not gate generic event delivery on:

crm.write

Introduce:

events.publish

Then destination-specific capabilities:

crm.odoo.write

communications.email.send

communications.sms.send

workflow.n8n.invoke

financial provider capabilities remain separate.

---

# WORK PACKAGE 5
## integration/durable-inbox

Existing webhook persistence is not enough.

Implement an inbox worker.

### integration_inbox

id
provider
external_event_id
event_type
schema_version
tenant_id
payload
payload_hash
correlation_id
signature_valid
received_at
status
attempts
locked_by
locked_until
next_attempt_at
processed_at
last_error

Unique:

provider + external_event_id

States:

RECEIVED
PROCESSING
RETRYABLE
PROCESSED
QUARANTINED
FAILED_TERMINAL

### HTTP webhook behavior

Verify raw body first.

Then:

authentication
signature
timestamp
replay window
event ID
tenant/provider
dedupe
durable INSERT
COMMIT
return 202

Do not mutate financial/application state in webhook HTTP request.

### Worker

Inbox Worker
→ translator
→ typed domain command
→ command service
→ audit
→ outbox
→ commit

### Unknown events

Unknown event_type or schema_version:

QUARANTINED

Never silently ignore.

---

# WORK PACKAGE 6
## webhooks/provider-translators

Complete:

POST /api/v2/webhooks/codestra

POST /api/v2/webhooks/plaid

POST /api/v2/webhooks/middesk

POST /api/v2/webhooks/lenders/{lender_id}

POST /api/v2/webhooks/docusign

POST /api/v2/webhooks/odoo/actions

POST /api/v2/webhooks/communications/{provider}

POST /api/v2/webhooks/n8n

Optional only when contract supports it:

POST /api/v2/webhooks/experian

### Required shared envelope

{
  "event_id": "...",
  "event_type": "...",
  "schema_version": "1",
  "occurred_at": "...",
  "tenant_id": "...",
  "correlation_id": "...",
  "aggregate": {
    "type": "...",
    "id": "...",
    "version": 1
  },
  "payload": {}
}

### Odoo restriction

Odoo actions may translate only into allowlisted commands.

Examples allowed:

AssignSalesOwner
CreateCRMNote
RequestBorrowerFollowUp
AcknowledgeSalesException

Never:

ApproveApplication
AcceptOffer
MarkContractSigned
ConfirmFunding

---

# WORK PACKAGE 7
## documents/secure-pipeline

Current metadata/document foundation is insufficient.

Implement:

POST /api/v2/applications/{application_id}/documents/upload-sessions

POST /api/v2/documents/{document_id}/complete

GET /api/v2/documents/{document_id}

GET /api/v2/documents/{document_id}/download-url

POST /api/v2/documents/{document_id}/reviews

POST /api/v2/admin/documents/{document_id}/scan/retry

DELETE /api/v2/documents/{document_id}

### Upload lifecycle

PENDING_UPLOAD
→ UPLOADED
→ SCANNING
→ CLEAN
→ CLASSIFYING
→ CLASSIFIED
→ VERIFIED

Alternate:

SCANNING
→ INFECTED
→ QUARANTINED

### Complete endpoint verifies

authorized user
object belongs to expected bucket/key
content length
declared MIME
detected MIME
SHA-256 checksum
upload token/session
document ownership

### Malware scanner

Add interface:

MalwareScanner

Implement ClamAV adapter.

Quarantined/infected documents cannot:

be downloaded normally
count toward requirements
enter underwriting
be sent to lender
be processed by OCR/document intelligence

### Download URL

short-lived

authorized

audited

object CLEAN or higher

No permanent public URLs.

### Retention

Add:

retention_class
retain_until
legal_hold
deleted_at

---

# WORK PACKAGE 8
## pii/security-controls

Implement field-level access.

Permissions:

PII_VIEW_MASKED
PII_REVEAL
IDENTITY_VIEW
BANK_DETAIL_VIEW
CREDIT_VIEW

### Default response

SSN:
***-**-1234

EIN:
**-***6789

DOB:
masked

### Reveal flow

POST /api/v2/admin/pii/reveal

requires:

specific permission
resource access
field allowlist
reason
request ID
correlation ID

Creates immutable audit:

PII_REVEALED

### Encryption

Encrypted fields store:

ciphertext
key_version
last4

Implement key-rotation service.

Never write decrypted PII into:

logs
Odoo
Codestra event payloads
n8n
Klyrow
Telnexa
operational exceptions

---

# WORK PACKAGE 9
## lenders/submissions

Implement:

POST /api/v2/applications/{application_id}/lender-submissions

POST /api/v2/lender-submissions/{submission_id}/send

POST /api/v2/lender-submissions/{submission_id}/retry

GET /api/v2/lender-submissions/{submission_id}/status

GET /api/v2/lender-submissions/{submission_id}/conditions

POST /api/v2/conditions/{condition_id}/decisions

### Send/retry require

Idempotency-Key
If-Match
permission
lender mapping profile version
capability
provider READY
application state
audit

### Provider POST retries

Do not blindly retry POST.

Only retry automatically when:

provider supports idempotency key
or
MoneyBee can prove request was not accepted

Otherwise create operational exception:

LENDER_SUBMISSION_UNCERTAIN

Require reconciliation/manual recovery.

---

# WORK PACKAGE 10
## contracts

Implement canonical endpoints:

POST /api/v2/applications/{application_id}/contracts

POST /api/v2/contracts/{contract_id}/send

GET /api/v2/contracts/{contract_id}/status

### Commands require

Idempotency-Key where mutation can call provider

If-Match

permission

accepted offer

conditions satisfied/waived

capability enabled

DocuSign READY

audit

event

### State

DRAFT
READY
SENDING
SENT
SIGNING
SIGNED
FAILED

Signed state should normally be set by verified provider webhook/inbox command.

Human operators must not manually mark signed except authorized recovery procedure.

---

# WORK PACKAGE 11
## funding/dual-control

Implement:

POST /api/v2/fundings/{funding_id}/approve

POST /api/v2/fundings/{funding_id}/send

POST /api/v2/fundings/{funding_id}/confirm

POST /api/v2/fundings/{funding_id}/reconcile

### All require

Idempotency-Key
If-Match
permission
audit
correlation ID

### Separation of duties

Store:

approved_by
approved_at

sent_by
sent_at

confirmed_by
confirmed_at

reconciled_by
reconciled_at

Rules:

approved_by != confirmed_by

Configurable stronger rule:

approved_by != sent_by
sent_by != confirmed_by

### Confirm requires

funding APPROVED/FUNDS_SENT according to workflow

signed contract

all conditions satisfied/waived

funded amount > 0

provider reference

capability enabled

provider READY

not already confirmed

### Immutable history

funding_status_history

No destructive mutation of historical funding facts.

### Reconciliation

Compare:

MoneyBee
lender provider
accounting projection
commission

Mismatch → operational exception.

---

# WORK PACKAGE 12
## operations/recovery

Implement:

GET /api/v2/admin/outbox/{event_id}/attempts

POST /api/v2/admin/outbox/{event_id}/retry

POST /api/v2/admin/outbox/{event_id}/replay

POST /api/v2/admin/inbox/{message_id}/retry

POST /api/v2/admin/operational-exceptions/{id}/assign

POST /api/v2/admin/operational-exceptions/{id}/comments

POST /api/v2/admin/operational-exceptions/{id}/retry

### Replay

Replay is privileged.

Requires:

INTEGRATION_REPLAY permission

reason

audit

idempotency protection

financial-side-effect safeguard

A replay must never create duplicate:

offer acceptance
contract
funding
commission
lender submission

---

# WORK PACKAGE 13
## api-consistency

Define one error envelope:

{
  "error": {
    "code": "CONCURRENT_MODIFICATION",
    "title": "Resource changed",
    "detail": "...",
    "request_id": "...",
    "retryable": false,
    "context": {}
  }
}

### Standardize

cursor pagination

Decimal serialization as strings

timestamps ISO-8601 UTC

ETag / If-Match

Idempotency-Key

429 format

payload size limits

request timeout semantics

API version/deprecation headers

stable machine error codes

---

# WORK PACKAGE 14
## observability

Implement OpenTelemetry.

Trace:

FastAPI
SQLAlchemy/PostgreSQL
Redis
outbox worker
inbox worker
Codestra
Plaid
Middesk
Odoo
Experian
lenders
DocuSign

### Structured log fields

timestamp
level
service
request_id
correlation_id
event_id
aggregate_type
aggregate_id
provider
duration_ms

Never log secrets/PII.

### Metrics

http latency/errors

DB pool utilization

worker heartbeat

outbox pending

outbox retry

outbox terminal failure

inbox pending

inbox retry

webhook invalid-signature

provider latency

provider 429

provider 5xx

document quarantine count

application funnel

matching latency

zero-match rate

lender response time

funding volume

commission outstanding

### Alerts

API unavailable

DB unavailable

worker missing heartbeat

outbox backlog

inbox backlog

invalid webhook spike

provider error spike

document infection

funding mismatch

commission mismatch

backup failed

restore rehearsal failed

---

# WORK PACKAGE 15
## postgres-production-tests

CI must run against real PostgreSQL.

Required test categories:

tenant isolation

record ownership

row locking

If-Match races

idempotency races

duplicate webhooks

worker crash

lease expiry

multiple workers

offer acceptance race

funding confirm race

condition decision race

lender callback race

No production readiness claim based only on SQLite tests.

---

# WORK PACKAGE 16
## staging-recovery-release

Create:

development
staging
production

Separate:

database
Redis
storage
Keycloak client
Odoo DB
Codestra identity
provider sandbox credentials

### Backup

PostgreSQL automated backup

encrypted

off-host

checksum

retention

PITR/WAL

### Restore rehearsal

restore into isolated database

verify checksum

verify migration head

boot API

run smoke tests

record result

destroy isolated environment

### Release evidence

SOURCE_SHA

IMAGE_DIGEST

MIGRATION_HEAD

CONFIG_CHECKSUM

SBOM_DIGEST

PROVENANCE/SIGNATURE

BACKUP_REFERENCE

### Deployment

CI
→ immutable image
→ staging
→ migrations
→ E2E
→ approval
→ backup
→ canary
→ production

Never deploy `latest`.

---

# LAUNCH GATE

Real funding must remain disabled until:

Keycloak frontend E2E PASS

local identity/tenancy PASS

PostgreSQL isolation PASS

concurrency PASS

inbox worker PASS

duplicate webhook PASS

document scan pipeline PASS

lender sandbox lifecycle PASS

contract webhook/signing lifecycle PASS

funding dual-control PASS

reconciliation PASS

observability alert exercise PASS

backup restore rehearsal PASS

staging canary PASS

immutable release evidence PASS

---

# FINAL REPORT

Return:

FINAL_STATUS

SOURCE_SHA

MIGRATION_HEAD

AUTH_STATUS

IDENTITY_BINDING_STATUS

TENANCY_STATUS

AUTHORIZATION_STATUS

COMMAND_STATUS

IDEMPOTENCY_STATUS

CONCURRENCY_STATUS

OUTBOX_STATUS

INBOX_STATUS

WEBHOOK_STATUS

DOCUMENT_SECURITY_STATUS

PII_STATUS

LENDER_STATUS

CONTRACT_STATUS

FUNDING_STATUS

OBSERVABILITY_STATUS

POSTGRES_TEST_STATUS

BACKUP_STATUS

RESTORE_STATUS

STAGING_STATUS

SBOM_STATUS

CANARY_STATUS

BLOCKERS

NEXT_SAFE_ACTION

FINAL_STATUS must remain PARTIAL or BLOCKED if any mandatory gate fails.
