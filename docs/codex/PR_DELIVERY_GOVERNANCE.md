# MoneyBee PR Delivery Governance

Every implementation step must be delivered as an independently reviewable PR.

## Required PR Contents

Implementation

Migration where applicable

Rollback / forward-fix strategy

Unit tests

PostgreSQL integration tests where applicable

Security tests

Concurrency tests where applicable

OpenAPI changes

Operational documentation

Readiness evidence

Known limitations

## Forbidden Automation

Codex must not:

auto-merge

enable auto-merge

deploy production

enable live financial capabilities

bypass branch protection

force-push over reviewed work

manually modify production DB

set FINAL_STATUS=READY from an individual PR

## Required PR Status

Every implementation PR reports:

PR_READINESS_STATUS = PASS | PARTIAL | BLOCKED

OVERALL_SYSTEM_STATUS = PARTIAL

LIVE_CAPABILITIES_ENABLED = NONE

## Migration Policy

Use:

expand
→ compatible deployment
→ backfill
→ validate
→ contract

Every migration includes:

head before
head after
empty DB → head test
current head → new head test
PostgreSQL test
rollback/forward-fix notes

Do not use metadata create-all as the production migration mechanism.

## PostgreSQL Requirement

Any feature relying on:

transactions
row locks
concurrency
SKIP LOCKED
unique constraints
partial indexes
leases
JSONB
database isolation

must have PostgreSQL tests.

SQLite does not count.

## OpenAPI Requirement

Any API-changing PR must document:

role/permission

tenant/record access

starting state

resulting state

Idempotency-Key

If-Match

audit fields

events emitted

error codes

rate limits

payload limits

manual recovery

OpenAPI drift must fail CI.

## Security Requirement

Negative tests are required for:

authentication
authorization
tenancy
PII
financial commands
webhooks
documents
integration recovery

## Rollback Requirement

Document:

code rollback

schema compatibility

configuration rollback

worker rollback

provider impact

data/backfill impact

whether downgrade is safe

whether forward-fix is preferred

## Capability Freeze

The following remain disabled:

credit.live_pull

lenders.live_submission

esign.live_send

funding.live_confirmation

payments

payouts

No CI-green PR may change this.

