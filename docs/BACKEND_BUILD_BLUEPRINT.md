# MoneyBee Backend Build Blueprint

This blueprint adds implementation detail to the approved backend specification. The API contract and security/compliance rules are authoritative whenever an illustrative example differs.

## Application layout

```text
app/
  main.py
  config.py
  core/
    auth.py
    permissions.py
    database.py
    models.py
    events.py
    exceptions.py
    security.py
    audit.py
    telemetry.py
  modules/
    leads/
    applications/
    businesses/
    owners/
    documents/
    banking/
    verification/
    underwriting/
    lenders/
    matching/
    offers/
    contracts/
    funding/
    communications/
    crm/
    consent/
    compliance/
    reporting/
    users/
  integrations/
    codestra_middleware/
    crm/
    lenders/
    plaid/
    kyb/
    identity/
    credit/
    esign/
    sms/
    email/
  workers/
    outbox_worker.py
    crm_worker.py
    lender_worker.py
    communication_worker.py
    document_worker.py
    underwriting_worker.py
migrations/
openapi/
tests/
infra/
alembic.ini
pyproject.toml
Dockerfile
docker-compose.yml
```

Use FastAPI application/router composition. Settings are validated at startup; production refuses placeholder, legacy issuer, missing encryption, or unsafe CORS configuration.

```python
def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="MoneyBeeLoans API",
        version="1.0.0",
        openapi_url="/openapi.json",
        docs_url="/docs" if settings.docs_enabled else None,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Request-ID",
        ],
    )
    include_v1_routers(app)
    register_problem_handlers(app)
    register_observability(app)
    return app
```

Allowlisted production origins:

- `https://moneybeeloans.com`
- `https://www.moneybeeloans.com`
- `https://app.moneybeeloans.com`
- `https://lenders.moneybeeloans.com`
- `https://admin.moneybeeloans.com`

Liveness checks only the process/event loop. Readiness checks migration compatibility and required dependencies with strict timeouts. Neither leaks configuration.

## Database foundation

Use SQLAlchemy 2 async patterns and transaction-scoped sessions.

```python
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

Use database/server-generated timezone-aware timestamps. Public identifiers are UUID/ULID. Monetary fields use `Numeric`/Decimal plus currency, not binary floats. Every tenant-owned table carries tenant scope. Important mutable aggregates carry a version column.

Core tables include users/roles/permissions/memberships, leads/attribution, businesses/addresses, applications/status history, owners/token references, consents/versions, documents, bank connections/accounts/analyses, business/identity verification, credit requests/results, lenders/users/programs/rules, matches, submissions, underwriting reviews/conditions, offers, contracts, funding, commissions, CRM links/events, communications, adverse actions, audit/webhook/outbox events, and a separately permissioned Section 1071 subsystem.

## Transactional lead creation

The public request must atomically create:

```text
Lead
Business prospect
Attribution
Consent evidence
Idempotency record
Outbox event
```

Then return `202 Accepted` with a stable lead/reference ID. CRM and communications run after commit.

```python
async with session.begin():
    prior = await idempotency.find_or_reserve(
        key=idempotency_key,
        scope="public.prequalification",
        request_hash=request_hash,
    )
    if prior.completed:
        return prior.response

    lead = await lead_repository.create(normalized_input)
    await attribution_repository.record(lead.id, attribution)
    await consent_service.record(lead.id, consents)
    await outbox.add(
        event_type="LeadSubmitted",
        aggregate_type="lead",
        aggregate_id=lead.id,
        payload_version=1,
        payload={"lead_id": str(lead.id)},
    )
    await idempotency.complete(prior, accepted_response)
```

Duplicate-lead resolution is distinct from HTTP idempotency. Normalize email/phone before bounded duplicate matching, preserve new attribution/consent evidence, and use an auditable merge/link policy.

## Outbox, queues, and workers

```text
Domain transaction
  → PostgreSQL outbox
  → leased outbox publisher
  → Service Bus
  → CRM / lender / email / SMS / document workers
  → success, retry, or DLQ
```

Each worker:

- atomically leases a bounded batch with owner and expiration;
- heartbeats/renews long work;
- verifies idempotency before side effects;
- records attempt, category, response code, safe response summary, next retry, and trace ID;
- uses exponential backoff with jitter;
- releases or expires abandoned leases;
- sends exhausted events to a DLQ;
- exposes backlog, oldest age, active leases, attempts, successes, retry categories, and DLQ count;
- supports audited admin replay without mutating the original evidence.

Database leasing is mandatory before horizontal scaling.

## CRM and Codestra middleware adapter

Use a provider protocol:

```python
class CRMProvider(Protocol):
    async def upsert_contact(self, command: UpsertContact) -> CRMContact: ...
    async def upsert_business(self, command: UpsertBusiness) -> CRMBusiness: ...
    async def create_opportunity(self, command: CreateOpportunity) -> CRMOpportunity: ...
    async def update_opportunity(self, command: UpdateOpportunity) -> CRMOpportunity: ...
    async def create_task(self, command: CreateTask) -> CRMTask: ...
    async def add_note(self, command: AddNote) -> CRMNote: ...
```

Production implementation is `CodestraMiddlewareCRMProvider`. It uses the approved internal Codestra middleware endpoint, short-lived Keycloak Client Credentials token, strict audience, mTLS on the private service lane when enabled, request ID, event ID, idempotency key, timeouts, and an egress allowlist. Do not use a static API key spread through application code.

Outbound sequence:

```text
LeadSubmitted
  → upsert contact
  → upsert business
  → create/update opportunity
  → sync assignment/task
  → record CRM links
```

Every operation is individually idempotent. Sanitized provider failures are retained; failed events are never discarded.

Inbound `/webhooks/crm` verifies signature/mTLS, timestamp, replay window, event ID, schema version, provider and tenant. It maps supported events through the application transition service; it never writes pipeline status directly around domain rules.

## Application state machine

Canonical V1 flow:

```text
LEAD
APPLICATION_STARTED
APPLICATION_IN_PROGRESS
APPLICATION_COMPLETE
VERIFICATION_PENDING
READY_FOR_MATCHING
MATCHED
SUBMITTED_TO_LENDERS
UNDERWRITING
OFFERS_AVAILABLE
OFFER_ACCEPTED
CONDITIONS_PENDING
CONTRACTING
APPROVED_FOR_FUNDING
FUNDED
CLOSED
```

Alternate/terminal states:

```text
DECLINED
WITHDRAWN
EXPIRED
DUPLICATE
FRAUD_REVIEW
```

Each transition defines allowed source states, actor/permission, preconditions, side effects, compliance actions, outbox events, and audit event. Frontend and CRM cannot arbitrarily assign status.

The requirements engine returns authoritative completion percentage, individual requirement state, blocking reasons, and next actions. It includes business, owner, financial, document, bank, verification, consent, disclosure, and jurisdiction/product requirements.

## Documents, banking, and verification

Documents: authorize upload session, direct encrypted object upload, checksum, malware scan/quarantine, classify, verify, and authorize short-lived access. Metadata remains in PostgreSQL. Every download is audited.

Banking adapter normalizes provider data to fields such as average monthly deposits, average daily balance, deposit count, negative days, NSF count, revenue/cash-flow trends, existing-payment patterns, and risk flags. Matching consumes the normalized model, not raw provider payloads.

Business verification normalizes registration, tax ID match, address match, watchlist status, business status, risk flags, and manual review. Provider payload storage is minimized and retention-controlled.

Credit access requires permission, documented permissible purpose, consent/authorization, provider adapter, field encryption, access audit, and adverse-action linkage. No generic ungoverned credit-pull endpoint is permitted.

## Lenders, programs, matching, and submissions

Lenders are isolated tenants. A lender sees an application only after an authorized MoneyBee submission. Programs are effective-dated and versioned, containing product, amounts, revenue, time-in-business, credit, existing positions, states, allowed/excluded industries, bank/risk requirements, and submission configuration.

Matching evaluates deterministic rules first:

```text
requested amount
monthly/annual revenue
time in business
state and product availability
industry
use of funds
bank-analysis values
credit range when authorized
existing positions
risk constraints
document readiness
product fit
```

Do not use protected characteristics. Persist eligible/ineligible result, score, reasons, rule/program version, inputs snapshot/hash, and expiration. Human underwriting remains in V1. Compensation cannot be the undisclosed sole ranking factor.

Lender adapters implement submit application, get status, get offers, upload authorized documents, and withdraw. Provide portal, API partner, manual, and mock adapters. Submission packages are minimum-necessary, consent-authorized, versioned, idempotent, and audited.

## Offers, contracts, and funding

Offer fields:

```text
application/lender/program
product
amount/currency
term
payment frequency/amount
interest rate
APR where applicable
factor rate where applicable
origination and other fees
total repayment
collateral
personal guarantee
prepayment terms
conditions
expiration
disclosure version
status/version
```

Statuses: `DRAFT`, `SUBMITTED`, `AVAILABLE`, `ACCEPTED`, `DECLINED`, `EXPIRED`, `WITHDRAWN`.

Acceptance locks the expected offer version, exact offer snapshot, disclosure snapshot/hash, consent evidence, timestamp, actor, IP/request ID, and transition. Contracts/e-sign and funding confirmation are server-side adapter/webhook workflows. Funding and commission updates are reconciled and idempotent. Production money movement remains disabled unless explicitly implemented and separately approved.

## RBAC

Role templates:

```text
CLIENT_ADMIN
CLIENT_USER
LENDER_ADMIN
LENDER_UNDERWRITER
LENDER_OPERATIONS
MONEYBEE_ADMIN
MONEYBEE_SALES
MONEYBEE_UNDERWRITER
MONEYBEE_OPERATIONS
MONEYBEE_COMPLIANCE
MONEYBEE_ACCOUNTING
MONEYBEE_SUPPORT
```

Representative permissions:

```text
lead.read
lead.assign
application.read
application.edit
application.submit
document.read
document.upload
lender.manage
program.manage
offer.create
offer.accept
underwriting.review
funding.approve
compliance.read
compliance.1071.read
user.manage
```

Enforcement combines token validation, active internal user, tenant membership, effective permission, resource ownership/assignment, and field-level policy. Authorization is required on every protected route and service method; list queries are scoped at the database/query layer.

## Compliance and audit

The compliance engine resolves jurisdiction, product, transaction type, lender, required disclosures, consents, and notices. Store document/disclosure version, exact rendered text or immutable artifact/hash, acceptance timestamp, actor, IP, user agent, request ID, and method.

Adverse action is a structured module with approved reason codes/templates, human review where required, timing/delivery evidence, and immutable history. Do not allow arbitrary salesperson-written denial notices.

Section 1071 data uses separate restricted tables and `compliance.1071.read`; it never appears in sales, underwriting, or matching views.

Audit events cover credit pulls, bank access, owner PII, document access, lender submission, underwriting decision, offers, funding, permissions, CRM delivery, webhook replay, and configuration change.

## Environment template

```bash
APP_ENV=local
DATABASE_URL=postgresql+asyncpg://moneybee:moneybee@postgres:5432/moneybee
REDIS_URL=redis://redis:6379/0

OIDC_ISSUER=https://auth.codestra.co/realms/codestra
OIDC_AUDIENCE=moneybee-api
OIDC_JWKS_URL=https://auth.codestra.co/realms/codestra/protocol/openid-connect/certs

CODESTRA_MIDDLEWARE_BASE_URL=
CODESTRA_MIDDLEWARE_TOKEN_URL=https://auth.codestra.co/realms/codestra/protocol/openid-connect/token
CODESTRA_MIDDLEWARE_CLIENT_ID=
CODESTRA_MIDDLEWARE_CLIENT_SECRET=
CODESTRA_MIDDLEWARE_MTLS_CERT_PATH=
CODESTRA_MIDDLEWARE_MTLS_KEY_PATH=
CODESTRA_MIDDLEWARE_CA_PATH=

BANK_PROVIDER_CLIENT_ID=
BANK_PROVIDER_SECRET=
KYB_PROVIDER_API_KEY=
IDENTITY_PROVIDER_API_KEY=
CREDIT_PROVIDER_API_KEY=
ESIGN_PROVIDER_API_KEY=
SMS_PROVIDER_API_KEY=
EMAIL_PROVIDER_API_KEY=

AZURE_STORAGE_ACCOUNT=
AZURE_SERVICE_BUS_CONNECTION_STRING=
FIELD_ENCRYPTION_KEY_ID=
```

This is an example key inventory, not a place for real values. Production secrets live in the approved secret manager. Startup must reject the legacy issuer and placeholder/insecure settings.

## Local development

Docker Compose provides PostgreSQL, Redis, API, worker, and approved local queue/storage emulators. Use health checks and persistent named volumes. Do not embed production-compatible default passwords outside local-only profiles.

Mocks required before live integrations:

- MockCRMProvider
- MockBankProvider
- MockKYBProvider
- MockIdentityProvider
- MockCreditProvider
- MockLenderProvider
- MockESignProvider
- MockEmailProvider
- MockSMSProvider

A synthetic test must run application → mock bank → mock verification → matching → mock lender → offer → acceptance → mock contract → funded → CRM sync without real borrower data or credentials.

## Implementation order

1. Backend foundation, settings, database, migrations, errors, telemetry, Docker, CI.
2. OIDC validation, tenant registry integration, RBAC, audit.
3. Public lead API, idempotency, attribution, consent, transactional outbox.
4. Leased workers and Codestra middleware/MockCRM adapters.
5. Application, businesses, owners, requirements, timeline.
6. Documents and secure object storage.
7. Banking and verification adapters/webhooks.
8. Lenders, programs, matching, submissions, lender API.
9. Offers, conditions, disclosures, acceptance.
10. Contracts/e-sign, funding, commission, reconciliation.
11. Admin APIs, CRM/DLQ center, reporting, marketing attribution.
12. Compliance, adverse action, restricted PII/1071.
13. Unit, integration, contract, E2E, authorization/tenant, migration, restore, load, and security tests.
14. Staging synthetic certification, immutable release, provider canaries, rollback rehearsal, and production approval.

V1 is complete only when the full synthetic lead-to-funded transaction succeeds with audit evidence and all external delivery remains fail-closed until explicitly certified.
