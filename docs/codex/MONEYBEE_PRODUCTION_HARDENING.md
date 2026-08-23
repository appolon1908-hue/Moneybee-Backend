# MoneyBee Production Hardening
## Codex Implementation Specification

Status: APPROVED
Current readiness: PARTIAL


## Authoritative Implementation Order

This sequence overrides the work-package numbering below. Work packages remain mandatory and are executed within these gates.

1. Keycloak frontend login/session
2. Local identity + organization/tenant binding
3. Durable inbox worker + typed webhook translators
4. Outbox subscriptions/deliveries instead of one global Codestra route
5. Commands + If-Match + concurrency for all financial mutations
6. Secure document upload/scan/download pipeline
7. Funding dual-control + separation of duties
8. PII reveal/masking/key rotation
9. PostgreSQL concurrency/tenant/webhook-race tests
10. Observability
11. Staging + backup/PITR + restore rehearsal
12. Immutable CI/CD + SBOM/provenance/canary

Tests accompany every step. Step 9 is the comprehensive PostgreSQL certification gate. Steps involving funding use sandbox providers and synthetic data until PII controls and every later launch gate pass.


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
