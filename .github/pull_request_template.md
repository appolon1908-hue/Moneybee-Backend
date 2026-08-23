# MoneyBee Pull Request

## Work Package

`<step/work-package>`

## Purpose

Describe the single production capability implemented by this PR.

## Implementation

Describe code changes.

## Database Migration

Migration required:

YES / NO

Migration head before:

`...`

Migration head after:

`...`

## Rollback / Forward Fix

Code rollback:

...

Schema compatibility:

...

Downgrade safe:

YES / NO

Forward-fix preferred:

YES / NO

## OpenAPI Changes

...

## Authentication / Authorization

Required roles/permissions:

...

Tenant/resource ownership rules:

...

## Idempotency

Required:

YES / NO

Behavior:

...

## Concurrency

If-Match required:

YES / NO

Aggregate version:

...

PostgreSQL race tests:

...

## Events

Events emitted:

...

Outbox destinations:

...

Inbox/webhook changes:

...

## Unit Tests

PASS / FAIL

Evidence:

...

## PostgreSQL Integration Tests

PASS / FAIL / N/A

Evidence:

...

## Security Tests

PASS / FAIL / N/A

Evidence:

...

## Concurrency Tests

PASS / FAIL / N/A

Evidence:

...

## E2E

PASS / FAIL / N/A

Evidence:

...

## Operational Documentation

Health signal:

...

Metrics:

...

Alerts:

...

Recovery procedure:

...

## Readiness Evidence

PR_READINESS_STATUS = PASS / PARTIAL / BLOCKED

OVERALL_SYSTEM_STATUS = PARTIAL

LIVE_CAPABILITIES_ENABLED = NONE

## Known Limitations

...

## Blockers

...

## Explicit Governance Confirmation

- [ ] This PR does not auto-enable a financial capability.
- [ ] This PR is not automatically merged.
- [ ] This PR does not deploy production merely because CI passed.
- [ ] PostgreSQL tests were used where PostgreSQL behavior matters.
- [ ] Rollback/forward-fix is documented.
- [ ] Readiness remains PARTIAL or BLOCKED.

