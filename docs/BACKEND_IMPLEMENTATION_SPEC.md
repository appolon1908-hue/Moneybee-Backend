# MoneyBee Backend Implementation Specification

Status: approved planning baseline  
Repository: `appolon1908-hue/Moneybee-Backend`  
Frontend dependency: `appolon1908-hue/Moneybee-frontend-`

## 1. Mission and authority

Build MoneyBeeLoans as a Python/FastAPI modular monolith with isolated workers and adapter-based integrations. PostgreSQL is the application system of record. The backend decides what is allowed and what actually happens.

The CRM receives sales/contact fields, pipeline status, tasks, opportunity values, notes, and assignments. It does not own applications, documents, consents, bank data, lender offers, underwriting, funding, compliance, or audit history.

All landing pages and portals use the same versioned API. Every inbound lead is committed locally before asynchronous CRM/middleware delivery so an external outage cannot lose it.

## 2. Technology and structure

- Python 3.13
- FastAPI and Pydantic v2
- SQLAlchemy 2 async
- Alembic
- PostgreSQL
- Redis
- Azure Service Bus or an adapter-compatible local broker
- Azure Blob Storage or S3-compatible local development storage
- dedicated asynchronous workers
- OpenTelemetry, structured JSON logs, metrics, traces
- pytest, Ruff, mypy/pyright, Bandit, dependency/secret/container scans
- Docker/Compose for local development

```text
app/
  main.py
  core/
    auth/
    security/
    database/
    messaging/
    encryption/
    audit/
    observability/
  modules/
    leads/
    applications/
    borrowers/
    businesses/
    owners/
    lenders/
    programs/
    underwriting/
    matching/
    offers/
    documents/
    bank_data/
    verification/
    compliance/
    consent/
    funding/
    payments/
    commissions/
    crm/
    communications/
    reporting/
    users/
  integrations/
    crm/
    codestra_middleware/
    plaid/
    kyb/
    identity/
    credit/
    lenders/
    docusign/
    email/
    sms/
    analytics/
  workers/
migrations/
tests/
openapi/
infra/
```

Module boundaries expose services/interfaces rather than importing another module's database internals. Begin as a modular monolith; extract services only when scale, failure isolation, or team ownership justifies it.

## 3. Request, auth, and tenant boundary

- Public API: `https://api.moneybeeloans.com/api/v2`
- Gateway path: Caddy/edge → Kong → FastAPI
- Canonical issuer: `https://auth.codestra.co/realms/codestra`
- Human clients: Authorization Code + PKCE S256
- Machine integrations: short-lived Client Credentials tokens and mTLS on private service lanes when configured
- remove/reject `auth.codestra.agency` in configuration, tests, and documentation
- validate issuer, audience, signature, expiration, not-before, and authorized party
- map subject to internal user/tenant membership
- enforce permissions and row/tenant scope on every protected operation
- default deny; do not trust frontend role claims
- rate limit public, authenticated, webhook, document, and administrative surfaces separately

Generate/request a correlation ID. Mutating endpoints use an idempotency key where duplicate execution is harmful. Errors use `application/problem+json` compatible with RFC 9457 and never disclose internals or PII.

## 4. Core domain

### Leads and prequalification

`POST /api/v2/public/prequalifications` must:

1. validate the payload and consent version;
2. apply anti-bot, rate, and fraud checks;
3. normalize email, E.164 phone, postal code, enums, and monetary fields;
4. resolve a bounded duplicate policy;
5. transactionally create/update lead, business prospect, attribution, consent, and outbox event;
6. return a stable lead/reference ID;
7. publish `LeadSubmitted` only through the transactional outbox;
8. route/assign the lead using backend rules;
9. deliver to Codestra middleware/CRM asynchronously;
10. queue approved borrower email/SMS notifications.

Never make lead acceptance depend on CRM availability.

### Applications

Own progressive business, financial, ownership, document, consent, and status workflows. Application state changes must use an explicit transition policy and append `application_status_history`. Standard pipeline:

`NEW_LEAD → CONTACTED → APPLICATION_STARTED → APPLICATION_COMPLETE → DOCUMENTS_PENDING → READY_FOR_MATCHING → SUBMITTED → UNDERWRITING → OFFER_RECEIVED → OFFER_ACCEPTED → CONTRACTING → FUNDING → FUNDED`

Terminal/exception states include `DECLINED`, `WITHDRAWN`, `DUPLICATE`, `UNRESPONSIVE`, `EXPIRED`, and `FRAUD_REVIEW`.

Enforce required fields and consents at submission, not merely save. Changes after submission follow revision/review rules.

### Documents

Store metadata in PostgreSQL and binary objects in object storage. Uploads use short-lived, content-limited upload sessions. Enforce file type/size, malware scanning, checksum, tenant prefix, encryption, quarantine, classification, verification, access logging, retention, and authorized download URLs.

### Bank data and verification

Plaid flow:

1. authenticated frontend requests backend link token;
2. backend creates link session;
3. frontend hosts Plaid Link;
4. public token is exchanged only by backend;
5. signed/idempotent Plaid webhooks update connections and ingestion jobs;
6. analyses are versioned and reviewable.

KYB/KYC adapters support Middesk, Persona, Socure, or an approved equivalent. Store provider references and normalized results, not unbounded raw payloads. TIN, sanctions, registration, business status, identity, and manual review states require audit history.

### Lenders, programs, and matching

Lenders are isolated tenants with authorized users. Programs define product, amount limits, revenue, time in business, credit range, states, industries/exclusions, existing-position limits, risk constraints, effective dates, and versioned rules.

The matching engine evaluates:

- program eligibility
- jurisdiction and compliance filters
- product fit
- risk filters
- requested amount and capacity
- document/data readiness
- explicit, versioned score components

Persist explanations and the exact rule/program versions used. Never rank secretly by compensation alone. V1 is rules + data + human underwriting, not an autonomous black-box approval engine.

### Offers, contracts, funding, and commissions

Offer data includes product, amount, term, rate/factor, APR where applicable, payment amount/frequency, origination/other fees, total repayment, prepayment terms, collateral, guarantee, conditions, expiration, disclosure version, and status.

State transitions are authorized and audited. Borrower acceptance records immutable offer/disclosure snapshots and consent. E-sign uses a server-side provider adapter/webhooks. Funding confirmation and commissions require reconciliation and idempotent events; no production money movement is enabled until vendor, legal, security, and launch approvals are documented.

## 5. CRM and Codestra middleware

Define a neutral interface:

```python
class CRMProvider(Protocol):
    async def upsert_contact(self, ...): ...
    async def upsert_company(self, ...): ...
    async def create_lead(self, ...): ...
    async def create_opportunity(self, ...): ...
    async def update_opportunity(self, ...): ...
    async def add_note(self, ...): ...
    async def create_task(self, ...): ...
```

Adapters may include Salesforce, HubSpot, GoHighLevel, Zoho, MockCRM, and ExistingMiddlewareCRMProvider. Production delivery to the user's CRM must flow through the approved Codestra middleware contract.

CRM payload mapping includes:

- lead ID and application URL/status
- contact and business sales fields
- revenue, time in business, amount, use of funds
- assigned specialist/team
- source, page, UTM fields, GCLID, FBCLID
- lender/offer/funding status
- funded amount and commission where authorized

Each integration event records `event_id`, `idempotency_key`, type/version, attempt, status, creation/sent timestamps, response code, sanitized response summary, next retry, and trace ID. Use database leasing/locking so workers scale horizontally without double claims. Apply exponential backoff with jitter and a bounded retry policy. Exhausted events enter a dead-letter queue.

Admin actions: inspect, correct permitted mapping/configuration, retry, and replay. Replay creates an audit event and preserves the original event.

Inbound CRM webhook: `POST /api/v2/webhooks/crm`. Verify signature/mTLS as configured, timestamp, replay window, event ID, schema version, and tenant/provider. Handle `LeadAssigned`, `LeadContacted`, `ApplicationRequested`, `ApplicationReceived`, `DocumentsRequested`, `OfferReceived`, `OfferAccepted`, `Declined`, `Funded`, and `Lost` through explicit transition rules.

## 6. Data model

Core tables:

- `users`, `roles`, `permissions`, memberships and sessions/revocations
- `leads`, `lead_sources`, `lead_attribution`
- `borrowers`, `businesses`, `business_addresses`
- `owners`, `owner_identity_tokens`
- `applications`, `application_status_history`, `application_consents`
- `documents`, `document_requirements`
- `bank_connections`, `bank_accounts`, `bank_analyses`
- `business_verifications`, `identity_verifications`
- `lenders`, `lender_users`, `lender_programs`, `lender_rules`
- `application_matches`, `lender_submissions`
- `underwriting_reviews`, `underwriting_conditions`
- `offers`, `contracts`, `fundings`, `payments`, `commissions`
- `crm_links`, `crm_events`
- `emails`, `sms_messages`
- `disclosures`, `disclosure_acceptances`, `adverse_actions`
- `audit_events`, `integration_events`, `webhook_events`, `outbox_events`

Every tenant-owned table has tenant/lender ownership, timestamps, and indexes aligned to query patterns. Use UUID/ULID public identifiers; do not expose sequential database keys. Monetary values use fixed-precision decimal plus currency. Important records use optimistic concurrency/version fields. Deletion/retention policies must preserve legally required history.

## 7. Sensitive data and security

Frontend never receives vendor secrets, database credentials, unnecessary SSN, raw credit files, or unrestricted bank data.

Required controls:

- secrets in Key Vault or approved secret manager; managed identity where available
- TLS everywhere and mTLS for approved private service lanes
- envelope/field encryption or tokenization for SSN/TIN and similarly sensitive identifiers
- masked display by default
- per-field/record access logging
- least-privilege database roles and service identities
- immutable/tamper-evident audit export
- webhook secret rotation and dual-key windows
- SSRF protection for callbacks/imports, strict egress allowlists, file scanning
- backup encryption, tested point-in-time restore, disaster-recovery runbook
- dependency, secret, SAST, container, IaC, and DAST checks
- no sensitive values in logs, traces, metrics, analytics, errors, queues, or test fixtures

Audit events record actor, action, time, target/application, previous/new sanitized value or hash, IP, user agent, request ID, reason, and authorization context. Audit application changes, bank connections, credit authorization/pull, lender submission, offer creation/change/acceptance, document access, SSN access, permission changes, CRM transmission, underwriting/funding decisions, and administrative replay.

## 8. Compliance-ready architecture

Production requirements depend on MoneyBee's legal role, products, states, and partners. Lending counsel must approve workflows before launch. Software must support:

- ECOA/Regulation B and business adverse-action workflows
- FCRA permissible-purpose authorization and notifications
- state commercial-financing disclosures
- consent versioning and evidence
- e-sign records
- TCPA/marketing consent and suppression
- CAN-SPAM
- privacy requests and retention
- licensing/routing restrictions

Build `1071_data` as a separately permissioned and encrypted subsystem when applicable. Do not expose protected demographic data in underwriting, matching, or sales dashboards. Do not implement a generic “pull credit” action without documented authorization, permissible purpose, audit, provider response handling, and adverse-action linkage.

Disclosures are versioned by product, jurisdiction, effective date, language, and presentation context. Offer acceptance records the exact rendered disclosure/version. Adverse actions are first-class objects with reasons, required timing, template version, delivery evidence, and human review.

## 9. Integrations and local adapters

Interfaces must support approved providers without coupling domain logic:

| Capability | Initial adapter |
|---|---|
| Bank data | Plaid |
| KYB | Middesk |
| Identity | Persona/Middesk/Socure |
| Credit | approved CRA/provider |
| E-sign | DocuSign |
| SMS | Twilio or Codestra/Telnexa adapter |
| Email | Postmark/SendGrid/Azure Communication Services or Codestra/Klyrow |
| CRM | Codestra middleware |
| Storage | Azure Blob |
| Analytics | PostHog/GA4 events without PII |
| Error telemetry | Sentry/OpenTelemetry |

Local/CI must run with MockCRM, MockLender, MockCredit, MockPlaid, MockKYB, MockESign, MockEmail, and MockSMS. No test depends on live credentials or real financial/identity data.

## 10. Infrastructure and operations

Environments: local, dev, staging, production.

Target Azure topology may use Front Door + WAF, Container Apps, PostgreSQL Flexible Server, Redis, Service Bus, Blob Storage, Key Vault, Application Insights, and Log Analytics. Preserve portability through interfaces and environment-specific deployment modules. Public ingress terminates only through the approved edge/gateway; admin/provider ports are private.

Operational endpoints:

- liveness: process can respond
- readiness: required local dependencies and migrations are ready
- startup: bounded initialization
- metrics: private/authenticated
- version/build metadata without secrets

Migrations use expand/contract compatibility, review, backup, rollback/forward-fix plan, and staging rehearsal. Workers expose backlog, age, claim, retry, failure, and DLQ metrics. Alerts cover elevated errors, latency, auth failures, webhook signature failures, queue age, delivery failures, and backup/restore status.

## 11. Delivery gates

1. Foundation: FastAPI, database, Redis, authentication, gateway contract, OpenAPI, logs/traces, Docker, CI.
2. Landing flow: prequalification, attribution, consent, spam protection, transactional outbox, routing, middleware/CRM delivery.
3. Borrower domain: accounts, progressive application, owners, documents, consents, progress/messages.
4. Banking/KYB: Link, exchange, ingestion, signed webhooks, analyses, verification, manual review.
5. Lender network: lender tenants/users, programs, versioned rules, matching, submissions, portal APIs.
6. Offers: conditions, comparison, acceptance, expiration, disclosures.
7. Admin operations: pipeline, underwriting, matching, routing, CRM/DLQ, communications, RBAC, audit.
8. Contract/funding: e-sign, final conditions, confirmation, reconciliation, commission, notifications, CRM update.
9. Compliance: consent evidence, credit authorization, disclosure engine, adverse action, state rules, retention, restricted PII, 1071-ready subsystem.
10. Reporting: marketing/sales funnels, lender performance, offers, funding, commissions, attribution.
11. Security: authorization/tenant tests, penetration test, PII review, secret controls, rate limits/WAF, backup and restore, DR, audit review, dependency/container/IaC scans.
12. Launch certification: complete synthetic journey from lead through closed deal, immutable release/SBOM/provenance, approved production configuration, provider certification, canary, monitoring, and tested rollback.

No gate is complete without code, migration/contract, automated tests, observability, security review, operational runbook, and captured evidence. Production integrations and funding remain fail-closed until their specific approvals and credentials are present.
