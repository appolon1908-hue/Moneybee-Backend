# MoneyBee API V2 Completion Ledger

This ledger records required work that is not yet fully implemented. P0 items are release blockers. It must not be read as evidence that a listed provider or production capability is active.

### 1. Full `/api/v2` implementation — P0

The following API groups still need to be fully coded, tested, and connected to PostgreSQL:

- `/public` 
- `/me` 
- `/borrower` 
- `/applications` 
- `/bank` 
- `/documents` 
- `/verification` 
- `/credit` 
- `/fraud` 
- `/matches` 
- `/lender/submissions` 
- `/conditions` 
- `/offers` 
- `/contracts` 
- `/funding` 
- `/commissions` 
- `/renewals` 
- `/communications` 
- `/crm` 
- `/affiliates` 
- `/complaints` 
- `/compliance` 
- `/reports` 
- `/audit-events` 
- `/capabilities` 
- `/webhooks` 

The endpoint inventory is defined, but each needs real:

```
```

```
router
↓
schema
↓
service
↓
policy
↓
repository
↓
database
```

---

### 2. Production database migrations — P0

We have the target schema, but we still need actual Alembic migration files.

For example:

```
```

```
0001_identity.py
0002_leads.py
0003_applications.py
0004_businesses_owners.py
0005_banking.py
0006_documents.py
0007_verification.py
0008_fraud.py
0009_lenders.py
0010_lender_program_versions.py
0011_matching.py
0012_submissions.py
0013_conditions.py
0014_offers.py
0015_contracts.py
0016_funding.py
0017_commissions.py
0018_compliance.py
0019_outbox.py
0020_audit.py
```

Production should be able to run:

```
```

```
alembic upgrade head
```

against an empty PostgreSQL database and build the entire schema correctly.

---

### 3. Real authentication — P0

The debug-role approach must disappear in production.

We still need:

```
```

```
OIDC/OAuth authentication
MFA
access tokens
refresh/session handling
logout
account recovery
session revocation
device/session list
```

And backend validation for:

```
```

```
issuer
audience
signature
expiration
roles
organization
permissions
```

---

### 4. Record-level authorization — P0

RBAC alone is not enough.

For example:

A borrower can have:

```
```

```
application.read
```

but must still only access **their own application**.

A lender underwriter can have:

```
```

```
lender.application.read
```

but only applications submitted to **their lender organization**.

Every repository/service needs resource authorization.

---

### 5. Capability-gating implementation — P0

We designed this, but it still needs real code.

Database:

```
```

```
capability_flags
provider_connections
```

Backend checks:

```
```

```
permission
+
capability enabled
+
provider ready
+
correct application state
```

Examples initially disabled:

```
```

```
credit.live_pull = false

lenders.live_submission = false

esign.live_send = false

communications.live_sms = false

funding.live_confirmation = false
```

This is one of the most important safety mechanisms.

---

### 6. Idempotency middleware — P0

Still needs implementation.

Required for:

```
```

```
application submission
lender submission
offer acceptance
contract creation
funding confirmation
commission receipt
CRM record creation
```

Every sensitive POST should support:

```
```

```
Idempotency-Key: <uuid>
```

---

### 7. Transactional outbox — P0

The conceptual design exists.

The production implementation still needs:

```
```

```
outbox_events
worker locking
retry scheduling
exponential backoff
dead-letter state
event replay
event deduplication
monitoring
```

For example:

```
```

```
OfferAccepted
       ↓
DB transaction
       ↓
Outbox
       ↓
CRM worker
       ↓
Notification worker
       ↓
Lender worker
```

---

### 8. Real CRM middleware integration — P0

The generic adapter is designed, but we still need **your CRM's actual contract**.

We need mappings for:

```
```

```
Lead
Contact
Business
Opportunity
Application status
Lender
Offer
Funding
Commission
Assigned salesperson
Campaign attribution
```

And inbound webhooks from CRM back into MoneyBee.

---

### 9. Real banking provider — P0/P1

The mock bank provider needs replacing.

Production implementation needs:

```
```

```
link-session creation
token exchange
webhooks
account sync
transaction sync
statement retrieval
connection refresh
disconnect
error recovery
```

Then normalization into:

```
```

```
average_monthly_deposits
average_daily_balance
NSF count
negative days
cash-flow trend
existing obligations
```

---

### 10. KYB/KYC provider — P0

Need real implementation for:

```
```

```
business registration
EIN/TIN validation
business address
owner identity
sanctions/watchlists
fraud signals
```

Provider data must normalize into MoneyBee's own model.

---

### 11. Credit provider — P0, but disabled by default

The endpoint can exist.

The live provider must **not activate** until the legal/compliance workflow is ready.

Need:

```
```

```
authorization record
permissible-purpose checks
credit-request adapter
credit-result normalization
access controls
audit logs
adverse-action integration
```

---

### 12. Fraud engine — P0

We defined the architecture but still need actual rules and persistence.

Initial version should detect:

```
```

```
duplicate business
duplicate EIN token
duplicate owner
duplicate bank account
email velocity
phone velocity
IP velocity
bank-owner mismatch
KYB mismatch
document mismatch
suspicious repeated submissions
```

Admin needs a manual review queue.

---

### 13. Lender-program rule engine — P0

We still need a proper rules engine around:

```
```

```
lender_program_versions
lender_program_rules
```

Rules should support:

```
```

```
min/max amount
monthly revenue
annual revenue
time in business
state
industry
product
bank metrics
credit thresholds
existing positions
excluded industries
```

And every decision must retain the rule version.

---

### 14. Explainable matching — P0

The matching API needs implementation beyond a simple score.

We need:

```
```

```
eligibility
+
score
+
reason codes
+
policy version
```

Example:

```
```

```
Eligible: YES
Score: 92

Reasons:
+ Revenue exceeds threshold
+ State supported
+ Product supported
+ Time in business sufficient

Warnings:
- Existing obligations near maximum
```

---

### 15. Underwriting workspace — P1

Still missing:

```
```

```
manual review queue
underwriter notes
decision history
policy version
reason codes
documents
bank analysis
fraud assessment
credit data
KYB results
```

---

### 16. Conditions engine — P0

Needs real implementation.

Borrower:

```
```

```
Condition requested
↓
Upload / answer
↓
Submit
```

Lender:

```
```

```
Review
↓
Approve / Reject / Waive
```

MoneyBee:

```
```

```
Audit entire lifecycle
```

---

### 17. Offer normalization — P0

The backend still needs normalization across lender products.

Every offer should normalize:

```
```

```
amount
term
payment frequency
payment amount
APR
factor rate
origination fee
other fees
total repayment
collateral
personal guarantee
prepayment terms
expiration
```

---

### 18. Contract/e-sign integration — P0 before funding

Still missing:

```
```

```
contract templates
template versions
signer management
e-sign provider adapter
webhook handling
signed-document storage
document hash
signature timeline
```

---

### 19. Funding reconciliation — P0

Very important.

Need real workflow:

```
```

```
Offer accepted
↓
Conditions complete
↓
Contract signed
↓
Approved for funding
↓
Funds sent
↓
Funding confirmed
```

Then reconcile:

```
```

```
MoneyBee
↕
Lender
↕
CRM
↕
Accounting
```

---

### 20. Commission engine — P1

Still needs:

```
```

```
expected commission
actual commission
salesperson split
affiliate split
adjustments
clawbacks
received date
reconciliation
```

---

### 21. Renewals — P1

Need a scheduled worker to evaluate funded borrowers.

```
```

```
funding
↓
time passes
↓
renewal rules
↓
eligible
↓
CRM opportunity
↓
borrower notification
```

---

### 22. Document security — P0

Local disk upload is not production-ready.

Need:

```
```

```
private object storage
upload authorization
quarantine
malware scanning
MIME verification
hashing
classification
OCR
access audit
retention
```

For Hetzner, you can use S3-compatible object storage rather than keeping documents on the application server.

---

### 23. PII encryption — P0

Raw:

```
```

```
SSN
DOB
EIN
```

must not simply sit in PostgreSQL.

Need:

```
```

```
application-layer encryption
key rotation
ciphertext storage
last-4 fields
restricted reveal permissions
access auditing
```

---

### 24. Compliance engine — P0

Still needs actual configurable rules for:

```
```

```
disclosures
consents
credit authorization
state requirements
product requirements
lender requirements
retention
adverse action
restricted reporting data
```

This must be versioned and effective-dated.

---

### 25. Adverse-action workflow — P0 where applicable

Need:

```
```

```
structured reason codes
template generation
notice delivery
delivery record
archive
audit
```

Not free-form salesperson text.

---

### 26. Affiliate portal/system — P1

Still missing if you plan to buy or receive external leads.

Need:

```
```

```
affiliate accounts
tracking links
lead attribution
funded deals
commission calculations
fraud rate
conversion rate
approved marketing assets
```

---

### 27. Communications center — P1

Need:

```
```

```
email provider
SMS provider
templates
message history
notification preferences
delivery status
bounce/failure handling
opt-out controls
```

---

### 28. Reporting backend — P1

Need actual aggregation endpoints and indexes for:

```
```

```
visitor → lead
lead → application
application → match
match → submission
submission → offer
offer → accepted
accepted → funded
```

Break down by:

```
```

```
lender
product
salesperson
state
industry
landing page
campaign
affiliate
```

---

### 29. Search — P1

Admin needs global search across:

```
```

```
lead ID
application ID
business
owner
phone
email
lender
funding
CRM ID
```

---

### 30. Reconciliation system — P0

One of the biggest remaining backend systems.

Scheduled checks:

```
```

```
MoneyBee vs CRM
MoneyBee vs lenders
MoneyBee vs funding
MoneyBee vs commissions
MoneyBee vs accounting
```

Admin page:

```
```

```
RECONCILIATION

Run                 Status
CRM daily            ✓

Lender A             3 mismatches

Funding              ✓

Commissions          2 missing
```

---

### 31. Production logging and observability — P0

Need:

```
```

```
structured JSON logs
request IDs
trace IDs
OpenTelemetry
error tracking
API latency
worker failures
queue age
provider latency
database health
disk usage
```

On Hetzner I would add:

```
```

```
Grafana
Loki
Prometheus
```

or use a managed observability provider.

---

### 32. Rate limiting — P0

Particularly for:

```
```

```
login
prequalification
password recovery
document upload
credit requests
webhooks
```

Redis can support distributed limits.

---

### 33. Webhook security — P0

Every provider webhook needs:

```
```

```
signature validation
timestamp validation
event deduplication
raw payload hash
provider event ID
replay protection
```

---

### 34. PostgreSQL production configuration — P0

Need proper:

```
```

```
connection limits
pool sizing
slow-query logging
vacuum strategy
indexes
statistics
backup
PITR
```

Also, PostgreSQL should not be accessible publicly.

---

### 35. Database indexes — P0/P1

At minimum:

```
```

```
leads(email)
leads(phone)
leads(status)
leads(created_at)

applications(status)
applications(lead_id)
applications(created_at)

owners(application_id)

documents(application_id, type)

bank_connections(application_id)

application_matches(application_id)

lender_submissions(application_id)
lender_submissions(lender_id)
lender_submissions(status)

offers(application_id)
offers(status)

fundings(status)

integration_events(status)
integration_events(provider)

audit_events(resource_type, resource_id)
audit_events(created_at)
```

---

### 36. Soft-delete / archival strategy — P1

Don't casually physically delete:

```
```

```
applications
offers
fundings
audit history
consents
```

Use:

```
```

```
archived_at
status
```

where appropriate.

---

### 37. Database backup/restore — P0

On your Hetzner server you need:

```
```

```
nightly encrypted database backup
+
off-server copy
+
retention policy
+
restore script
+
restore test
```

The backup must not exist only on `49.12.145.107`.

---

### 38. Hetzner hardening — P0

Your server still needs:

```
```

```
SSH key-only login
disable root password login
Hetzner firewall
automatic security updates
Docker installed from official repo
Fail2ban or equivalent
disk monitoring
backup monitoring
limited admin accounts
```

Public:

```
```

```
80
443
```

Restricted:

```
```

```
22
```

Private only:

```
```

```
5432
6379
8000
```

---

### 39. Caddy deployment — P0

Still need actual deployed Caddy config for:

```
```

```
moneybeeloan.com
app.moneybeeloan.com
lenders.moneybeeloan.com
admin.moneybeeloan.com
api.moneybeeloan.com
```

---

### 40. Git deployment automation — P1

Right now deployment is still manual.

I would add GitHub Actions:

```
```

```
main branch
↓
tests
↓
build
↓
SSH deploy
↓
git pull
↓
docker compose build
↓
alembic upgrade head
↓
docker compose up -d
↓
health test
```

