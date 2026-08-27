# MoneyBee Backend ↔ Middleware ↔ n8n Automation Handoff v2

## Exact contract lineage

```text
MoneyBee repository: appolon1908-hue/Moneybee-Backend
MoneyBee branch: integration/n8n-automation-v2
MoneyBee base SHA: 588a402f5339b1a836acbf468644ef4e330dcb18
Middleware contract SHA: bd6c7c0a470a74ef648fe2a21e2d9dcd4c2328a4
N8N contract SHA: e3a3e97ab0da0d7df78bba52b18904e5f83e6dbe
Production activation: NOT AUTHORIZED
```

## Authority boundary

MoneyBee Backend owns borrower, business, application, document, underwriting, offer, lender-route, disclosure, e-sign, funding, repayment, servicing, exception, audit, and product state.

n8n is not a financial system of record and must never connect directly to MoneyBee PostgreSQL, Redis, Keycloak administration, credit providers, lenders, banks, e-sign providers, funding providers, payment processors, Odoo, SMS, email, or document storage.

```text
MoneyBee business transaction
 -> MoneyBee transactional outbox
 -> Middleware durable inbox
 -> Middleware automation job
 -> n8n orchestration or approval coordination
 -> Middleware governed MoneyBee command
 -> MoneyBee API command handler
 -> MoneyBee read-back
 -> Middleware reconciliation
```

## Outbound events

Suggested versioned events:

```text
moneybee.application.submitted
moneybee.application.status_changed
moneybee.documents.missing
moneybee.documents.completed
moneybee.underwriting.review_requested
moneybee.underwriting.decision_recorded
moneybee.lender.route_requested
moneybee.lender.response_received
moneybee.offer.selected
moneybee.disclosure.ready
moneybee.esign.requested
moneybee.esign.completed
moneybee.funding.requested
moneybee.funding.status_changed
moneybee.payment.status_changed
moneybee.exception.created
privacy.preference.changed
```

Every event includes tenant, application identity, actor, correlation, causation, idempotency, event version, UTC timestamps, safe references, and no raw credentials or unrestricted PII.

## Inbound governed commands

Expose purpose-built command handlers rather than a generic unrestricted endpoint:

```text
create_application_activity
request_missing_document_notice
record_document_review_result
create_underwriting_task
record_approved_underwriting_decision
create_lender_route_plan
submit_to_approved_lender
record_lender_response
create_offer_notification
request_disclosure_generation
request_esign_envelope
record_esign_result
request_funding_operation
record_funding_result
create_servicing_task
create_operations_exception
record_delivery_result
record_crm_projection
```

Every command requires expected state/version, an idempotency key, tenant authorization, capability authorization, and destination read-back.

## Matching n8n workflows

```text
moneybee.application.intake.v1
moneybee.documents.missing-reminder.v1
moneybee.lender-route-approval.v1
moneybee.status-notification.v1
moneybee.funding-reconcile.v1
```

Source branch:

```text
appolon1908-hue/N8N:automation/moneybee-loans
```

## Capability freeze

These remain false until separate provider, staging, legal/compliance, rollback, and exact-SHA approval:

```text
CREDIT_LIVE_PULL=false
LENDERS_LIVE_SUBMISSION=false
ESIGN_LIVE_SEND=false
FUNDING_LIVE_EXECUTION=false
PAYMENT_EXECUTION=false
ENABLE_EXTERNAL_DELIVERY=false
ODOO_WRITE=false
```

An active workflow cannot override the capability engine.

## Human approvals

Require protected approval for:

```text
underwriting decision publication
lender submission
adverse-action communication
material offer change
live e-sign send
funding execution
payment/refund action
privacy deletion
operator dead-letter replay
```

A long approval wait is stored durably by Middleware/MoneyBee. n8n exits and resumes through a new job after approval.

## Idempotency and unknown outcomes

- Exact replay returns the original command/result.
- Changed payload under the same key returns `idempotency_conflict`.
- Concurrent duplicates produce one logical effect.
- A timeout is an unknown outcome.
- Lender, e-sign, funding, and payment adapters reconcile before any retry.
- Financial and destructive effects have no blind automatic compensation.

## Required tests

```text
cross-tenant denial
application state/version conflict
exact replay
conflicting replay
concurrent duplicate
capability disabled
approval rejected or expired
lender timeout reconciliation
provider webhook replay
PII redaction
Middleware outage recovery
n8n restart recovery
outbox/inbox durability
backup/restore
rollback rehearsal
zero external provider effects in staging
```

No application record, lender submission, credit pull, e-sign send, funding, payment, message, database, credential, container, workflow, or production service is changed by this documentation branch.
