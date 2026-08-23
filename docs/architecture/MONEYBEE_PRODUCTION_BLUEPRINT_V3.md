# MoneyBee Production Blueprint V3

Status: APPROVED ARCHITECTURE AUTHORITY

Overall system status: PARTIAL

This document is the MoneyBee-specific production architecture.

It replaces generic marketplace terminology with lending-specific domains and resolves previously conflicting design decisions.

---

# 1. Core Principle

MoneyBee owns business truth.

External systems integrate through controlled adapters and durable events.

Frontend and API layers are interfaces around authoritative domain logic.

MoneyBee is not a CRUD application.

It is a transactional lending workflow and operating platform.

---

# 2. Repository Boundary

The system remains separated into:

Moneybee-Backend
Moneybee-frontend-

Frontend never connects directly to:

PostgreSQL
Redis
Odoo
Codestra
Plaid
Middesk
Experian
lender APIs
DocuSign
Klyrow
Telnexa
n8n

The only frontend/backend contract is:

`/api/v2`

---

# 3. Production Architecture

MoneyBee Frontends
        |
        | HTTPS /api/v2
        v
FastAPI Transport Layer
        |
        v
Application Commands / Queries
        |
        v
Domain Services
   |       |       |
Policies  State   Authorization
         Machines
   |       |       |
   +-------+-------+
           |
           v
Repositories / Queries
           |
           v
PostgreSQL
   |        |        |         |
Audit   Idempotency Outbox   Inbox
                     |
                     v
                   Workers
                     |
          +----------+----------+
          |                     |
          v                     v
 Core Financial            Codestra
    Adapters                    |
          |                     +--> Odoo Community
          +--> Plaid            +--> Klyrow
          +--> Middesk          +--> Telnexa
          +--> Experian         +--> n8n
          +--> Lenders
          +--> DocuSign

Object Storage
      |
      v
Malware Scanner
      |
      v
Document Classification / Review

---

# 4. Thin API Rule

FastAPI routes may:

authenticate
resolve Principal
parse transport DTO
construct command/query
call application service
serialize response

Routes may not decide:

application eligibility
lender eligibility
fraud rules
underwriting rules
state transitions
funding authority
tenant ownership
provider behavior
document eligibility
commission calculations

Those belong in application/domain services.

---

# 5. MoneyBee Domains

Primary domains:

Identity
Organizations
Leads
Applications
Businesses
Owners
Financial Profiles
Documents
Banking
Business Verification
Identity Verification
Credit
Fraud
Lenders
Lender Programs
Matching
Lender Submissions
Underwriting
Conditions
Offers
Contracts
Funding
Commissions
Renewals
Communications
Compliance
Complaints
Affiliates
Integrations
Operations
Audit
Reporting

---

# 6. Application Commands

Every important mutation becomes a typed command.

Required high-value commands include:

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

Commands describe intent, not HTTP.

The same command may be invoked from:

HTTP API
inbox worker
scheduler
authorized admin action
approved Odoo callback
CLI recovery tool

---

# 7. Command Context

Every state-changing command receives:

Principal
organization / tenant
request ID
correlation ID
causation ID
idempotency key
expected aggregate version
IP address
user agent

This context is used consistently for:

authorization
audit
idempotency
tracing
event correlation
security investigation

---

# 8. Authentication

Identity provider:

Keycloak

Canonical issuer:

`https://auth.codestra.co/realms/codestra`

Human browser authentication:

Authorization Code + PKCE

Machine authentication:

Client Credentials where explicitly approved

JWT validation requires:

signature
issuer
audience
subject
expiration
issued-at
not-before
algorithm
key ID

JWKS rotation must be supported.

---

# 9. Local Identity Binding

MoneyBee authority uses:

`issuer + subject`

Never email.

Flow:

validated Keycloak identity
        |
        v
external_identity
        |
        v
local MoneyBee user
        |
        v
organization membership
        |
        v
roles + permissions
        |
        v
Principal

Unknown production identities must not receive privileges automatically.

---

# 10. Authorization

Authorization is:

authentication
+
permission
+
organization membership
+
resource ownership
+
lender membership
+
resource state

Examples:

Borrower A cannot read Borrower B's application.

Lender A cannot read Lender B's submission.

Sales staff cannot reveal SSNs unless separately authorized.

Odoo CRM users cannot confirm funding.

---

# 11. Capabilities

Sensitive capabilities remain fail-closed.

Effective capability requires:

code exists
AND
environment allows it
AND
release flag enabled
AND
dependency capabilities enabled
AND
provider connection READY
AND
governance approval

Code existence does not activate a capability.

---

# 12. Money Representation

Authoritative money representation:

PostgreSQL `NUMERIC(18,2)`

Never use binary floats for authoritative financial values.

API monetary values serialize as decimal strings.

Example:

`"50000.00"`

---

# 13. Idempotency

Required for high-value mutations.

Store:

actor
operation
idempotency key
request hash
status
result resource
response
created_at
expires_at

Canonical statuses:

IN_PROGRESS
COMPLETED
FAILED_RETRYABLE
FAILED_TERMINAL
EXPIRED

Rules:

same key + same logical request
→ same logical result

same key + different payload
→ 409 IDEMPOTENCY_KEY_REUSED

same key while IN_PROGRESS
→ 409 REQUEST_ALREADY_PROCESSING

---

# 14. Optimistic Concurrency

Protected aggregates maintain versions.

At minimum:

Application
LenderSubmission
UnderwritingCondition
Offer
Contract
Funding
Commission

Protected mutations require:

`If-Match`

Missing:

428 PRECONDITION_REQUIRED

Stale:

409 CONCURRENT_MODIFICATION

Use row locking where exclusivity is required.

Concurrency must be proven on PostgreSQL.

---

# 15. Atomic Transaction Rule

An important command commits atomically:

business state
+
history
+
audit
+
idempotency result
+
domain event/outbox event

Then COMMIT.

External systems are not called before the transaction commits.

---

# 16. State Machines

Application, lender submission, condition, offer, contract, funding and commission lifecycles each have explicit state machines.

No arbitrary status-column mutation.

Application example:

APPLICATION_STARTED
APPLICATION_IN_PROGRESS
APPLICATION_COMPLETE
VERIFICATION_PENDING
READY_FOR_MATCHING
MATCHED
SUBMITTED_TO_LENDERS
UNDERWRITING
CONDITIONS_PENDING
OFFERS_AVAILABLE
OFFER_ACCEPTED
CONTRACT_READY
CONTRACT_SENT
CONTRACT_SIGNED
APPROVED_FOR_FUNDING
FUNDS_SENT
FUNDED
CLOSED

Exception states:

FRAUD_REVIEW
COMPLIANCE_REVIEW
DECLINED
WITHDRAWN
EXPIRED
CANCELLED

---

# 17. Domain Events

Events use versioned contracts.

Examples:

lead.created.v1

application.started.v1
application.submitted.v1

bank.connected.v1
bank.analysis.completed.v1

business_verification.completed.v1

fraud.review_required.v1

application.matched.v1

lender_submission.created.v1
lender_submission.updated.v1

condition.requested.v1
condition.satisfied.v1

offer.received.v1
offer.accepted.v1

contract.sent.v1
contract.signed.v1

funding.sent.v1
funding.confirmed.v1

commission.received.v1

renewal.eligible.v1

Event envelope contains:

event ID
event type
schema version
occurred_at
aggregate type
aggregate ID
aggregate version
tenant/organization
correlation ID
causation ID
payload

Breaking contract changes require a new event version.

---

# 18. Transactional Outbox

Canonical outbox delivery states:

PENDING_CONFIGURATION
PENDING
PROCESSING
RETRYABLE
DELIVERED
FAILED_TERMINAL

Outbox delivery supports:

event subscriptions
per-destination delivery state
claim tokens
leases
retry scheduling
terminal failures
operator retry/replay
metrics

Do not force every event through Codestra.

Do not gate all integrations with `crm.write`.

Destination capabilities are separate.

---

# 19. Durable Inbox

Canonical inbox states:

RECEIVED
PROCESSING
RETRYABLE
PROCESSED
QUARANTINED
FAILED_TERMINAL

Incoming flow:

raw request
→ body-size guard
→ authentication/signature
→ timestamp/replay validation
→ provider/tenant validation
→ external event ID
→ dedupe
→ inbox write
→ COMMIT
→ 202
→ inbox worker
→ translator
→ typed domain command

Unique:

provider + external_event_id

Unknown event type or schema version:

QUARANTINED

---

# 20. Webhook Contract

Required webhook surfaces include:

/api/v2/webhooks/codestra

/api/v2/webhooks/plaid

/api/v2/webhooks/middesk

/api/v2/webhooks/lenders/{lender_id}

/api/v2/webhooks/docusign

/api/v2/webhooks/odoo/actions

/api/v2/webhooks/communications/{provider}

/api/v2/webhooks/n8n

Experian webhook only when supported by the contracted product.

Webhook handlers persist first and process asynchronously.

---

# 21. Adapter Layer

Provider-neutral interfaces include:

IdentityProvider
MiddlewareProvider
CrmProvider
BusinessVerificationProvider
CreditDataProvider
BankProvider
LenderProvider
ESignProvider
EmailProvider
SmsProvider
WorkflowProvider
ObjectStorage
MalwareScanner
PaymentProvider
PayoutProvider
AnalyticsSink

Vendor structures must not leak into domain logic.

---

# 22. Codestra Responsibility

Codestra is the integration/control plane.

Use Codestra for:

Odoo projections
Klyrow
Telnexa
n8n
approved accounting projection
analytics
enterprise integrations

Do not require Codestra synchronously for every core financial provider operation.

Core financial domain integrations remain governed directly by MoneyBee adapters when appropriate.

---

# 23. Odoo Community

Odoo is a CRM/sales projection.

Odoo may contain:

contacts
companies
sales opportunities
sales assignment
campaign attribution
activities
sales notes
follow-up tasks

Odoo must not contain:

SSNs
raw bank transactions
raw credit reports
fraud evidence
provider credentials
funding authority

Odoo callbacks may translate only into approved domain commands.

Odoo never writes directly to MoneyBee PostgreSQL.

---

# 24. Documents

File lifecycle:

PENDING_UPLOAD
→ UPLOADED
→ SCANNING
→ CLEAN
→ CLASSIFYING
→ CLASSIFIED
→ VERIFIED / REVIEW_REQUIRED

Malware:

SCANNING
→ INFECTED
→ QUARANTINED

Only safe states may enter underwriting.

Storage is private object storage.

Downloads are authorized, audited and short-lived.

---

# 25. PII Security

Sensitive fields are masked by default.

Examples:

SSN ***-**-1234
EIN **-***6789

Reveal requires:

specific permission
record authorization
field allowlist
reason
request/correlation ID

Reveals are audited.

Encrypted field storage includes:

ciphertext
key_version
last4

Implement key rotation.

---

# 26. Lending Compliance

Store authoritative evidence for:

credit authorization
consent version
accepted_at
permissible purpose
provider request ID
normalized decision reasons
adverse-action reasons
disclosure versions
disclosure acceptance
state/product eligibility
retention policy

Sensitive credit access receives stricter authorization.

---

# 27. Funding Separation of Duties

Funding mutations require controlled identities.

Store:

approved_by
approved_at
sent_by
sent_at
confirmed_by
confirmed_at
reconciled_by
reconciled_at

Minimum rule:

approved_by != confirmed_by

Recommended:

approved_by != sent_by
sent_by != confirmed_by

Funding history is immutable.

---

# 28. API Contract

Canonical error envelope:

{
  "error": {
    "code": "CONCURRENT_MODIFICATION",
    "title": "Resource changed",
    "detail": "Reload before retrying.",
    "request_id": "uuid",
    "retryable": false,
    "context": {}
  }
}

API conventions:

`/api/v2`

cursor pagination

ISO-8601 UTC timestamps

Decimal strings

ETag

If-Match

Idempotency-Key

stable machine error codes

deprecation policy

request/payload limits

---

# 29. Rate and Body Limits

Define separate policy for:

public acquisition endpoints
authenticated borrower/lender endpoints
admin endpoints
webhooks
uploads
financial commands

Kong may enforce edge-level controls.

FastAPI still enforces application safety limits.

---

# 30. Gateway Responsibility

Kong:

service/public gateway where deployed
JWT/OIDC validation where configured
mTLS
edge rate limits
request size
routing
correlation headers

Caddy:

TLS and reverse proxy for direct MoneyBee-hosted sites where applicable

Do not have overlapping public gateway authority without documented routing.

Trusted proxies must be explicitly configured.

---

# 31. PostgreSQL

PostgreSQL is authoritative.

Redis is not business truth.

Use Redis for:

rate limiting
cache
worker coordination
temporary locks
circuit-breaker support

Do not store authoritative lending state only in Redis.

PostGIS is not required unless MoneyBee later implements true geographic eligibility queries.

---

# 32. Operations

Operational failures become records.

Examples:

APPLICATION_STALE
BANK_SYNC_FAILED
KYB_REVIEW_REQUIRED
CREDIT_PROVIDER_FAILED
NO_ELIGIBLE_LENDER
LENDER_SUBMISSION_FAILED
LENDER_SUBMISSION_UNCERTAIN
CONDITION_OVERDUE
OFFER_EXPIRING
CONTRACT_UNSIGNED
FUNDING_DELAYED
FUNDING_MISMATCH
COMMISSION_MISMATCH
CRM_SYNC_FAILED
WEBHOOK_PROCESSING_FAILED
OUTBOX_RETRY_EXHAUSTED
DOCUMENT_INFECTED

Operations can:

view
assign
comment
acknowledge
retry
replay where safe
resolve

Normal recovery must not require direct DB editing.

---

# 33. Observability

Every request carries:

request ID
correlation ID

Implement:

structured logs
OpenTelemetry traces
metrics
alerts
worker heartbeat
provider latency/error metrics
outbox/inbox metrics
business funnel metrics

Never log:

JWTs
cookies
Authorization headers
SSNs
DOB
full EINs
credit reports
bank credentials
provider secrets

---

# 34. SLOs

Initial production targets:

API availability: 99.9%

interactive API p95:
< 500 ms excluding synchronous third-party latency

webhook durable acknowledgment p95:
< 1 second

normal outbox delivery:
99% within 5 minutes

normal inbox processing:
99% within 5 minutes

critical worker heartbeat:
alert after 2 minutes stale

Tune after load testing.

---

# 35. Accessibility

Frontend target:

WCAG 2.2 AA

Test:

keyboard navigation
focus management
labels
validation
contrast
screen readers
modals
responsive layouts

---

# 36. Environments

Maintain:

development
staging
production

Staging uses the same production candidate artifacts and architecture but separate:

PostgreSQL
Redis
object storage
Keycloak client
Odoo database
Codestra identity
provider sandbox credentials
capability configuration

---

# 37. Backup and Recovery

Production requires:

automated DB backup
encryption
off-host copy
checksums
retention
backup alerts
WAL / PITR

A backup is not successful until restore rehearsal succeeds.

Initial objectives:

RPO <= 15 minutes
RTO <= 4 hours

Business approval may revise these.

---

# 38. Restore Rehearsal

Automate:

create isolated PostgreSQL
restore backup
verify checksum
verify migration head
boot API
run smoke tests
record evidence
destroy environment

---

# 39. Immutable Releases

Release identity includes:

Git SHA
image digest
migration head
configuration checksum
SBOM digest
image signature
provenance
backup reference

Never deploy `latest` as release identity.

Frontend/backend are built independently from their own repositories.

Production compose must consume immutable artifacts, not build one repository from the other's filesystem.

---

# 40. CI/CD

PR flow:

lint
typecheck
unit/domain tests
PostgreSQL integration tests
migration tests
authorization tests
idempotency/concurrency tests
integration tests
OpenAPI drift test
secret scan
dependency audit
SAST
container scan
SBOM
immutable image build

Release:

staging
migration
smoke
E2E
human approval
backup
canary
production
monitored soak

---

# 41. Readiness Governance

Readiness is evidence-based.

Configuration alone does not prove AUTH.

No current dead outbox record does not prove outbox correctness.

Inbox persistence without an inbox worker does not prove inbox readiness.

Partial idempotency coverage does not prove idempotency readiness.

Evidence record:

gate
status
source_sha
environment
evidence_type
evidence_reference
generated_at
expires_at
approved_by

Through implementation:

OVERALL_SYSTEM_STATUS = PARTIAL

Mandatory gate failure:

FINAL_STATUS = BLOCKED

Only after:

all mandatory gates pass
AND
evidence is current
AND
human launch approval exists

may:

FINAL_STATUS = READY

---

# 42. Capability Freeze

During implementation:

credit.live_pull = false

lenders.live_submission = false

esign.live_send = false

funding.live_confirmation = false

payments = false

payouts = false

Capability activation is a separate post-certification action.

---

# 43. Definition of Done

MoneyBee is not production-ready until:

frontend authentication proven
local identity proven
tenant isolation proven
domain commands authoritative
idempotency proven
PostgreSQL concurrency proven
outbox proven
inbox proven
provider webhooks certified
documents secured
PII controls proven
lender lifecycle proven
contract lifecycle proven
funding dual-control proven
reconciliation proven
observability working
load testing completed
WCAG 2.2 AA target verified
backup/restore proven
PITR proven
staging passed
immutable release proven
canary passed
rollback defined
incident response exercised
human launch approval recorded

