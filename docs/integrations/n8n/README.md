# MoneyBee ↔ Middleware ↔ n8n automation integration

## Authority

MoneyBee owns lending truth. Odoo is a CRM projection, Codestra Middleware is the cross-system integration/control plane, and n8n executes only allowlisted workflows.

n8n must never write directly to MoneyBee PostgreSQL, Odoo, a lender, credit bureau, bank, e-sign provider, payment rail or document provider.

```text
MoneyBee durable domain event
  -> MoneyBee transactional outbox
  -> Middleware authenticated inbox
  -> canonical automation job
  -> n8n timing, branching and human review
  -> governed Middleware command
  -> MoneyBee or provider adapter
  -> destination read-back and reconciliation
  -> MoneyBee durable result event
```

## Events available to automation

```text
moneybee.application.submitted
moneybee.application.status_changed
moneybee.documents.missing
moneybee.documents.completed
moneybee.identity.review_required
moneybee.credit.review_required
moneybee.lender.route_requested
moneybee.lender.response_received
moneybee.esign.status_changed
moneybee.funding.status_changed
moneybee.payment.status_changed
moneybee.operational_exception.created
```

Events are emitted through a transactional outbox in the same database transaction as the MoneyBee business change.

## Commands requested through Middleware

```text
moneybee.application.create_task
moneybee.application.update_projection
moneybee.document.reminder_request
moneybee.identity.review_task
moneybee.credit.review_task
moneybee.lender.route_plan
moneybee.lender.submit_approved
moneybee.esign.send_approved
moneybee.funding.reconcile
moneybee.notification.request
moneybee.exception.assign
```

Unsafe provider POST operations are never automatically repeated unless the adapter proves stable provider idempotency. A timeout is an unknown result that requires provider reconciliation.

## Initial n8n workflows

```text
moneybee.application.intake.v1
moneybee.documents.missing-reminder.v1
moneybee.lender-route-approval.v1
moneybee.status-notification.v1
moneybee.funding-reconcile.v1
```

## Human approval requirements

- Identity and fraud review decisions remain in MoneyBee.
- Underwriter/lender routing approval is durable and auditable.
- n8n may coordinate the wait but cannot approve its own request.
- Two-person approval is required for any future financial capability activation or replay with financial effects.

## Capability freeze

```text
MONEYBEE_WRITE=false
CREDIT_LIVE_PULL=false
LENDERS_LIVE_SUBMISSION=false
ESIGN_LIVE_SEND=false
FUNDING_EXECUTION=false
PAYMENT_EXECUTION=false
ENABLE_EXTERNAL_DELIVERY=false
DEAD_LETTER_REPLAY=false
```

Workflow activation does not change these values.

## Security and data rules

- Keycloak `(issuer, subject)` is the immutable human identity.
- Every job and command is tenant scoped.
- n8n receives the minimum safe payload, not complete financial documents or credentials.
- Documents remain in approved secure storage and are referenced by opaque IDs.
- PII and financial details must not be stored in workflow exports or logs.
- Provider credentials remain in dedicated Middleware/MoneyBee adapters.
- Odoo receives only approved secret-free projections.
- Conflicting replays are rejected without mutating the original application state.

## Branch dependencies

```text
Moneybee-Backend/feature/financial-system-foundation
Middleware-/core/integration-contracts
Middleware-/core/event-ledger-outbox
Middleware-/core/webhook-inbox-replay
Middleware-/core/workers-scheduler
Middleware-/integration/keycloak
Middleware-/integration/n8n
N8N/contract/automation-control-plane-v2-20260827
N8N/shared/automation-runtime
N8N/automation/moneybee-loans
```

## Acceptance

```text
DIRECT_N8N_DATABASE_ACCESS=DENIED
DIRECT_N8N_PROVIDER_ACCESS=DENIED
TENANT_ISOLATION=PASS
EXACT_REPLAY=PASS
CONFLICTING_REPLAY=PASS
UNKNOWN_PROVIDER_OUTCOME_RECONCILED=PASS
UNSAFE_PROVIDER_POST_AUTO_RETRY=DENIED
LIVE_FINANCIAL_CAPABILITIES=DISABLED
WORKFLOWS_ACTIVE_IN_GIT=NO
PRODUCTION_CHANGED=NO
```
