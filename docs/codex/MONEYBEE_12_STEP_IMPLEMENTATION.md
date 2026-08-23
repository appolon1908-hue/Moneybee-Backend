# MoneyBee 12-Step Production Implementation

This is the authoritative implementation order.

Steps may not be reordered without explicit approval.

## Step 1A — Frontend Authentication

PR:

frontend/keycloak-pkce

Repository:

Moneybee-frontend-

Deliver:

Keycloak Authorization Code + PKCE
login/logout
callback
session handling
protected routes
token-provider wiring
401/403 behavior
ETag / If-Match support
correlation IDs

## Step 1B — Local Identity and Tenancy

PR:

auth/local-identity-tenancy

Repository:

Moneybee-Backend

Deliver:

users
external_identities
organizations
memberships
roles
permissions
Principal
issuer + subject binding
disabled-user enforcement
tenant isolation
PostgreSQL tests

Steps 1A and 1B are paired but separate PRs.

Both must be reviewable before Step 2.

## Step 2 — Command Architecture

PR:

commands/command-context

Deliver typed commands and shared CommandContext.

Move high-risk router mutations into application/domain services.

## Step 3 — Idempotency and Concurrency

PR:

concurrency/idempotency-versioning

Deliver:

transactional idempotency
aggregate versions
ETag
If-Match
428 missing precondition
409 stale version
row locks
PostgreSQL race tests

## Step 4 — Outbox Deliveries

PR:

integration/outbox-deliveries

Deliver:

event subscriptions
per-destination deliveries
claim token
lease
events.publish
destination capabilities
worker heartbeat

## Step 5 — Durable Inbox

PR:

integration/durable-inbox

Deliver:

canonical inbox
leasing
retries
quarantine
typed translators
async processing

Unify Plaid under the same durability model.

## Step 6 — Provider Webhook Translators

PR:

webhooks/provider-translators

Deliver:

Codestra
Plaid
Middesk
lenders
DocuSign
Odoo actions
communications
n8n
Experian only when contract supports it

All persist-first + 202 + asynchronous processing.

## Step 7 — Secure Documents

PR:

documents/secure-pipeline

Deliver:

presigned upload sessions
completion verification
MIME detection
checksums
ClamAV
quarantine
controlled downloads
reviews
retention

Unsafe documents cannot enter underwriting.

## Step 8 — PII and Compliance

PR:

pii/compliance-controls

Deliver:

masking
PII reveal permissions
reason-required reveal
reveal audit
key versioning
key rotation
credit consent
permissible purpose
disclosures
adverse action
retention controls

## Step 9 — Lenders, Contracts and Funding

PR family:

financial/lender-contract-funding

May be separated into smaller independently reviewable PRs.

Deliver:

lender send/retry/status
conditions
DocuSign lifecycle
funding approve/send/confirm/reconcile
dual control
immutable financial history

Live capabilities remain disabled.

## Step 10 — Operations and API Consistency

PR:

operations/api-consistency

Deliver:

outbox attempts/retry/replay
inbox retry
exception assign/comment/retry
canonical error envelope
cursor pagination
rate/body limits
API deprecation policy

## Step 11 — Observability and PostgreSQL Proof

PR:

observability/postgres-production-tests

Deliver:

OpenTelemetry
structured logs
metrics
alerts
worker heartbeat
PostgreSQL CI
concurrency tests
load tests
WCAG 2.2 AA evidence

## Step 12 — Staging, Recovery and Immutable Release

PR:

release/staging-recovery

Deliver:

staging
off-host backup
PITR
restore rehearsal
RPO/RTO
lockfiles
immutable image digests
SBOM
signing
provenance
canary
rollback evidence

## Final Launch Gate

Step 12 completion does not automatically mean READY.

Run the complete launch gate.

Only after all mandatory gates PASS and human launch approval exists may the readiness system become READY.

Capabilities are still activated separately.

