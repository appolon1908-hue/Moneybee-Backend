# MoneyBee Authority Boundaries

Status: architectural contract for implementation. This document does not enable live financial behavior and does not mark any later implementation step complete.

## System of record

MoneyBee owns lending truth and remains authoritative for lending and financial state, including:

- applications and application lifecycle
- bank transactions and banking-derived underwriting inputs
- KYB / business verification results
- credit results
- fraud and verification evidence
- lender matching decisions and selected program/version
- lender submission state
- offers and offer acceptance
- conditions
- contracts and signature state
- funding state and immutable funding history
- commission calculations, receipts, adjustments, splits, and reconciliation state
- operational financial exceptions
- readiness evidence and release/launch approval records

No downstream system may become authoritative merely because it received a projection, webhook, callback, or provider response.

## Odoo boundary

Odoo is a CRM projection only. It may receive customer/application/contact/activity/status projections through the transactional outbox, but it must not become authoritative for lending eligibility, underwriting, accepted offers, condition satisfaction, contract signature state, funding facts, commission truth, or final readiness.

A CRM write or sync failure must not roll back already committed MoneyBee business state. CRM delivery is independently retryable and observable.

## Codestra boundary

Codestra is an integration/control plane, not the lending system of record. It may route authorized events/commands, coordinate approved integrations, and carry non-sensitive projections, but MoneyBee must re-authorize inbound actions and translate them into typed domain commands before financial state changes.

Codestra events must not contain decrypted sensitive fields that are prohibited by the PII controls.

## External provider boundary

External providers connect through controlled adapters and durable event processing. Provider responses and webhooks are evidence/input to MoneyBee commands, not direct authority over MoneyBee aggregate state.

Inbound provider events must use authenticated, signed, timestamp-tolerant, replay-protected webhook handling and the durable integration inbox before a worker translates them into an authorized domain command.

Outbound financial provider operations must flow through MoneyBee-owned command, idempotency, concurrency, audit, capability, provider-readiness, and outbox/gateway controls. Unsafe provider POST operations must not be blindly retried. If the external result is uncertain, MoneyBee records an operational exception such as `LENDER_SUBMISSION_UNCERTAIN` and reconciles before another external financial effect is attempted.

## Financial API contract

The approved implementation sequence reserves the following `/api/v2` APIs for later independent financial PRs. They are architectural contracts here, not Step-0 implementation claims.

### Lender submissions

```http
POST /api/v2/applications/{application_id}/lender-submissions
POST /api/v2/lender-submissions/{submission_id}/send
POST /api/v2/lender-submissions/{submission_id}/retry
GET  /api/v2/lender-submissions/{submission_id}
GET  /api/v2/lender-submissions/{submission_id}/status
```

Send/retry requires, as applicable:

- `Idempotency-Key`
- `If-Match`
- authorized permission and tenant/resource access
- lender mapping/profile version
- `lenders.live_submission` capability
- provider `READY`
- valid application state
- audit and correlation context

The live capability remains disabled until lender sandbox certification and launch approval.

### Conditions

```http
GET  /api/v2/conditions/{id}
POST /api/v2/conditions/{id}/submit
POST /api/v2/conditions/{id}/decisions
GET  /api/v2/lender-submissions/{submission_id}/conditions
```

Condition decisions require an authorized actor, explicit state transition, reason, audit, aggregate version, and immutable/history evidence.

### Contracts

```http
POST /api/v2/applications/{application_id}/contracts
GET  /api/v2/contracts/{contract_id}
POST /api/v2/contracts/{contract_id}/send
GET  /api/v2/contracts/{contract_id}/status
```

Contract send requires, as applicable, `Idempotency-Key`, `If-Match`, permission, accepted offer, satisfied/waived conditions, e-sign capability, DocuSign readiness, audit, and domain event creation. Normal signature completion is driven by a verified provider webhook -> durable inbox -> domain command. `esign.live_send` remains disabled until certification.

### Funding with dual control

```http
GET  /api/v2/applications/{application_id}/funding
POST /api/v2/fundings/{funding_id}/approve
POST /api/v2/fundings/{funding_id}/send
POST /api/v2/fundings/{funding_id}/confirm
POST /api/v2/fundings/{funding_id}/reconcile
```

Every funding mutation requires `Idempotency-Key`, `If-Match`, permission, audit, and correlation context.

Persist separation-of-duty evidence:

- `approved_by`, `approved_at`
- `sent_by`, `sent_at`
- `confirmed_by`, `confirmed_at`
- `reconciled_by`, `reconciled_at`

Minimum separation rule:

```text
approved_by != confirmed_by
```

The stronger policy may also require `approved_by != sent_by` and `sent_by != confirmed_by`.

Funding confirmation requires correct funding state, signed contract, all conditions satisfied/waived, funded amount greater than zero, provider reference, provider readiness, enabled capability, and proof the funding is not already confirmed.

Funding history is immutable. Historical funding facts are not destructively rewritten. `funding.live_confirmation` remains disabled until certification.

### Commission and reconciliation

```http
GET  /api/v2/admin/commissions
GET  /api/v2/admin/commissions/{id}
POST /api/v2/admin/commissions/{id}/receipts
POST /api/v2/admin/commissions/{id}/adjustments
GET  /api/v2/admin/commissions/{id}/splits
```

Commission state is ledger-oriented. Previous expected/received values are not silently overwritten. Reconciliation compares:

- MoneyBee funding truth
- lender state
- accounting/CRM projection where relevant
- commission ledger

Mismatches create operational exceptions such as `FUNDING_MISMATCH` and `COMMISSION_MISMATCH` rather than silently normalizing conflicting records.

## Concurrency and idempotency invariant

Critical financial mutations use request-hashed idempotency and optimistic concurrency. The same idempotency key with a different request must conflict; concurrent state changes must use aggregate versions exposed through `ETag` and required with `If-Match` where specified.

Real PostgreSQL race tests are required. SQLite or mocked concurrency is not sufficient production evidence.

## Durable transaction invariant

For important commands, MoneyBee commits business state, history, audit, idempotency result, and outbox records in the same PostgreSQL transaction. External delivery happens only after commit. One failed destination cannot invalidate successfully committed MoneyBee business state.

## Release and readiness authority

Completing Step 12 does not make MoneyBee production-ready by itself. `FINAL_STATUS=READY` is permitted only when:

1. every mandatory launch gate is `PASS`;
2. all evidence is current and tied to the exact release candidate;
3. source SHA, image digests, migration head, configuration checksum, SBOM/signature/provenance and evidence snapshot match the candidate; and
4. an explicit human launch approval exists for that exact candidate.

Old evidence cannot prove a new release.

## Capability freeze

Throughout implementation, these remain disabled unless and until their separate controlled activation is authorized after the required evidence and dual approval:

```text
credit.live_pull=false
lenders.live_submission=false
esign.live_send=false
funding.live_confirmation=false
payments=false
payouts=false
```

This document must never be interpreted as authorization to enable them.
