# CODEX MISSION — MONEYBEE BUSINESS-LENDING PLATFORM

**Mission owner:** Ralph Appolon  
**Execution mode:** staging-first, fail-closed, evidence-driven  
**Date issued:** 2026-08-26  
**Production authorization:** NOT GRANTED

## Mission statement

Prepare, validate, package, and deploy the MoneyBee business-lending platform to a controlled staging environment. Finish the customer, lender/bank, and administrator web surfaces; make all public forms submit to authoritative MoneyBee APIs; deliver accepted CRM projections through the Codestra middleware to Odoo using durable outbox/inbox processing; and make inbound provider and middleware webhooks authenticated, replay-safe, deduplicated, observable, and recoverable.

Do not deploy a feature branch directly to production. Do not enable live credit pulls, live lender submissions, e-sign sends, funding confirmations, payments, payouts, SMS, email, Odoo writes, n8n delivery, or any other external side effect merely because code or CI passes. A passing build is evidence, not production approval.

The first permitted deployment target is **staging with all external and financial capabilities disabled**.

## Repositories and current consolidation heads

### Backend

Repository: `appolon1908-hue/Moneybee-Backend`

Current consolidated branch:

```text
release/portal-stack-consolidated
80e1129d5732b4f971e80849e33d51c971bafa3e
```

Consolidation PR:

```text
https://github.com/appolon1908-hue/Moneybee-Backend/pull/10
```

Required next backend feature branch:

```text
feature/business-lender-crm-delivery
```

### Frontend

Repository: `appolon1908-hue/Moneybee-frontend-`

Current consolidated branch:

```text
release/portal-stack-consolidated
e2b5f79763111177b7d19894eb9710cea56c546f
```

Consolidation PR:

```text
https://github.com/appolon1908-hue/Moneybee-frontend-/pull/13
```

Required next frontend feature branch:

```text
feature/business-lender-site-forms
```

## Source-control rules

1. Work only in the repository that owns the code.
2. Backend application, migrations, workers, integration contracts, webhooks, and deployment manifests belong in `Moneybee-Backend`.
3. Vue pages, forms, route definitions, typed API clients, validation, UI tests, and frontend Docker assets belong in `Moneybee-frontend-`.
4. Do not copy frontend source into the backend repository or backend source into the frontend repository.
5. Do not use GitHub Actions workflows that rewrite branches or auto-commit generated fixes.
6. Keep each PR focused and reviewable.
7. Do not merge PR #10 or PR #13 until their exact current heads are green and independently reviewed.
8. Do not close superseded PRs until their lineage is recorded in the replacement PRs.
9. Create protected branches:

```text
release/staging
release/production
```

10. Require pull requests, exact-head CI, independent approval, and no force pushes on release branches.
11. Build release artifacts only from the exact protected merged SHA.

## Clean PR sequence

### Backend sequence

```text
auth/local-identity-tenancy
    ↓
PR #10: release/portal-stack-consolidated
    ↓
feature/business-lender-crm-delivery
    ↓
release/staging
```

The CRM-delivery PR must contain only:

- public business-funding, contact, lender-partner, and referral-partner APIs;
- consent and attribution evidence;
- CRM projection models and migration;
- transactional outbox creation;
- Codestra delivery adapter;
- signed Codestra receipt webhook;
- inbox/outbox retry, replay, dead-letter, and requeue operations;
- Odoo-ready versioned event contract;
- integration and security tests;
- OpenAPI update;
- worker and deployment documentation.

### Frontend sequence

```text
frontend/keycloak-pkce
    ↓
PR #13: release/portal-stack-consolidated
    ↓
feature/business-lender-site-forms
    ↓
release/staging
```

The site/forms PR must contain only:

- public business-lending and lender-partner pages;
- customer-resource and legal routes;
- accessible production forms;
- typed clients for the reviewed backend contracts;
- customer, lender, and admin navigation updates;
- form unit, component, and browser tests;
- production frontend builds and images.

## Required public URLs

### Production targets

```text
https://moneybeeloan.com                 marketing and customer resources
https://www.moneybeeloan.com             canonical redirect or marketing alias
https://app.moneybeeloan.com             borrower/client portal
https://lenders.moneybeeloan.com         lender and bank portal
https://admin.moneybeeloan.com           MoneyBee admin/operations portal
https://api.moneybeeloan.com/api/v2      authoritative API
https://auth.codestra.co/realms/codestra canonical Keycloak authority
```

### Staging targets

Use approved DNS names, preferably:

```text
https://staging.moneybeeloan.com
https://app-staging.moneybeeloan.com
https://lenders-staging.moneybeeloan.com
https://admin-staging.moneybeeloan.com
https://api-staging.moneybeeloan.com/api/v2
```

Do not change production DNS until staging validation is complete.

## Required marketing and customer-resource pages

Keep the existing financing and industry pages and add the missing focused resources.

### Financing and industry pages

```text
/business-loans
/working-capital
/business-line-of-credit
/equipment-financing
/sba-loans
/fast-business-funding
/restaurant-financing
/trucking-business-loans
/construction-business-loans
/retail-business-loans
```

### Business-lender and partner pages

```text
/for-lenders
/lender-partners
/lender-programs
/submit-a-deal
/partner-with-us
/referral-partners
/brokers
/brokers/apply
```

### Customer resources and legal pages

```text
/how-it-works
/eligibility
/required-documents
/faq
/contact
/support
/security
/privacy
/terms
/consents-and-disclosures
/accessibility
/complaints
```

Legal, consent, disclosure, and privacy text must be presented as counsel-reviewable content and must not claim legal approval without evidence.

## Required public forms

Implement and validate these forms:

1. Business-funding prequalification.
2. General contact request.
3. Callback request.
4. Lender/bank partnership inquiry.
5. Broker/referral-partner application.
6. Deal-submission inquiry that creates a controlled intake record but does not submit to a live lender.

Every public mutation must include:

- `Idempotency-Key`;
- canonical request hash;
- duplicate-key replay returning the original result;
- conflict response when the same key is reused with a different payload;
- server-side validation and normalization;
- email normalization;
- phone normalization;
- UTM/referrer/affiliate attribution;
- consent type, document version, content hash, accepted timestamp, and source evidence;
- request/correlation IDs;
- rate limiting and bot-abuse controls;
- accessible validation messages;
- safe error responses without internal details;
- one authoritative database record, audit event, and outbox event in the same transaction.

## Required API endpoints

Keep `/api/v2` canonical. Proposed endpoint names may be adjusted only if the final OpenAPI contract remains coherent and all clients are regenerated.

### Public intake

```text
POST /api/v2/public/prequalifications
POST /api/v2/public/contact-requests
POST /api/v2/public/callback-requests
POST /api/v2/public/lender-partner-inquiries
POST /api/v2/public/referral-partner-inquiries
POST /api/v2/public/deal-submission-inquiries
```

Do not expose intake records by predictable reference alone. Any public continuation or status URL must use an opaque, expiring, one-time or otherwise appropriately protected token.

### CRM delivery administration

```text
GET  /api/v2/admin/crm-deliveries
GET  /api/v2/admin/crm-deliveries/{delivery_id}
POST /api/v2/admin/crm-deliveries/{delivery_id}/requeue
GET  /api/v2/admin/integration-health
GET  /api/v2/admin/integration-inbox
GET  /api/v2/admin/operational-exceptions
POST /api/v2/admin/operational-exceptions/{exception_id}/resolve
```

All admin routes require explicit local permissions, active MoneyBee membership, tenant/resource validation, optimistic versions where applicable, and audit records.

### Webhooks

```text
POST /api/v2/webhooks/codestra/receipts
POST /api/v2/webhooks/providers/{provider}
POST /api/v2/webhooks/middesk
POST /api/v2/webhooks/plaid
```

Each webhook must enforce:

- provider allowlist;
- JSON content type where applicable;
- request-size ceiling;
- timestamp/replay window;
- constant-time signature verification;
- secret rotation support;
- provider event-ID uniqueness;
- raw-body hash uniqueness and collision rejection;
- durable receipt before acknowledgment;
- bounded retry policy;
- dead-letter state;
- audited manual requeue;
- raw payload hidden from normal portal responses;
- no direct financial action from receipt intake.

## MoneyBee → Codestra → Odoo delivery contract

MoneyBee remains the lending system of record.

The required path is:

```text
MoneyBee command transaction
    → MoneyBee durable outbox
    → Codestra authenticated middleware endpoint
    → Codestra durable, deduplicated inbox
    → allowlisted Odoo CRM projection command
    → Odoo lead/contact/opportunity upsert
    → signed Codestra receipt
    → MoneyBee durable inbox
    → delivery marked DELIVERED or FAILED with evidence
```

Do not allow Odoo, n8n, or Codestra to write directly to MoneyBee PostgreSQL.

### Outbound authentication

Use OAuth 2.0 client credentials for machine identity and add a versioned HMAC-signed event envelope when required by the approved Codestra contract.

Each outbound event must contain at least:

```text
event_id
event_type
event_version
occurred_at
aggregate_type
aggregate_id
tenant_id
correlation_id
causation_id
idempotency_key
payload
```

### Odoo projection behavior

The Odoo bridge must upsert by stable MoneyBee identifiers, not by fuzzy names or email alone.

Project approved fields for:

- business name;
- contact name;
- normalized email and phone;
- requested amount;
- use of funds;
- time in business;
- monthly revenue;
- postal code;
- source landing page;
- UTM and affiliate attribution;
- MoneyBee intake/reference ID;
- intake type;
- current MoneyBee status;
- assigned MoneyBee owner where approved;
- consent evidence reference, not unrestricted raw compliance payloads.

Odoo must not overwrite MoneyBee application, underwriting, offer, funding, or compliance state.

## Capability freeze for staging

The following values must remain false or disabled during initial staging deployment:

```text
credit.live_pull=false
lenders.live_submission=false
esign.live_send=false
funding.live_confirmation=false
payments=false
payouts=false
ENABLE_EXTERNAL_DELIVERY=false
LIVE_WRITES=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false
communications.live_email=false
communications.live_sms=false
```

Forms may create authoritative MoneyBee records and pending outbox events. Disabled workers must leave those events pending; they must not consume, retry, or dead-letter them while delivery is disabled.

After staging validation, enable a **sandbox-only CRM delivery canary** through a separate approved change. Do not enable live lending or money movement.

## Docker release requirements

Keep frontend and backend releases separate.

### Required images

```text
ghcr.io/appolon1908-hue/moneybee-backend
ghcr.io/appolon1908-hue/moneybee-worker
ghcr.io/appolon1908-hue/moneybee-webhook-worker
ghcr.io/appolon1908-hue/moneybee-marketing
ghcr.io/appolon1908-hue/moneybee-borrower
ghcr.io/appolon1908-hue/moneybee-lender
ghcr.io/appolon1908-hue/moneybee-admin
```

Build each image from the exact protected merged SHA. Publish and deploy by immutable digest, not by mutable tags.

For every image produce:

- image digest;
- SBOM;
- vulnerability scan;
- provenance/attestation;
- signature and verification evidence;
- source SHA label;
- build timestamp;
- version endpoint or static release identity.

The production/staging server must not run `docker compose build`. It must only pull reviewed images by digest.

### Required release Compose services

```text
postgres
redis
migrate
api
worker
webhook-worker
marketing
borrower
lender
admin
caddy or approved edge proxy
```

The `migrate` service must run once and complete successfully before API/worker rollout. PostgreSQL and Redis must be private-only.

## Target-host gate

Do not assume a deployment host from old notes. In particular, do not deploy to `49.12.145.107` without first proving that the host is approved for MoneyBee; it has previously been associated with another controlled workload.

Before changing a server, record:

```text
hostname
public and private IPs
operating system
CPU/RAM/disk
running services
Docker version
listening ports
firewall rules
existing Caddy/Kong/Nginx ownership
existing databases and volumes
backup destination
DNS ownership
SSH access method
```

Abort the deployment if the host identity, ownership, available resources, or network role is unresolved.

## Keycloak requirements

Canonical authority:

```text
https://auth.codestra.co/realms/codestra
```

Use Authorization Code + PKCE S256 for browser portals. Do not put a client secret in a browser application.

Configure exact staging and production redirect, silent-callback, logout, and web-origin allowlists for borrower, lender, and admin portals.

Run browser E2E for:

- login;
- callback;
- logout;
- refresh;
- expired session;
- deep link;
- multi-organization selection;
- borrower/lender/admin role separation;
- denied tenant;
- denied permission;
- disabled user;
- inactive membership.

Frontend route guards are usability controls only. Backend local identity, memberships, permissions, tenant scope, and resource ownership remain authoritative.

## Database and migration gates

Use PostgreSQL 17 for staging and production-like evidence.

Required evidence:

```text
empty database → alembic head = PASS
current baseline → new head = PASS
head → controlled downgrade → head = PASS
production-like restored copy → head = PASS
backup = PASS
restore = PASS
RTO recorded
RPO recorded
single Alembic head confirmed
```

Do not use runtime schema auto-creation in staging or production.

## Validation matrix

### Backend

```text
RUFF=PASS
PYTHON_COMPILE=PASS
PYTEST=PASS
POSTGRES_INTEGRATION=PASS
TENANT_ISOLATION=PASS
RBAC_MATRIX=PASS
IDEMPOTENCY=PASS
CONCURRENCY=PASS
OPENAPI_DRIFT=PASS
MIGRATION_CYCLE=PASS
BACKEND_IMAGE_BUILD=PASS
WORKER_IMAGE_BUILD=PASS
WEBHOOK_WORKER_IMAGE_BUILD=PASS
```

### Frontend

```text
PNPM_LOCKFILE_COMMITTED=YES
PNPM_FROZEN_INSTALL=PASS
TYPESCRIPT=PASS
UNIT_TESTS=PASS
COMPONENT_TESTS=PASS
MARKETING_BUILD=PASS
BORROWER_BUILD=PASS
LENDER_BUILD=PASS
ADMIN_BUILD=PASS
ALL_FRONTEND_IMAGES=PASS
PLAYWRIGHT_E2E=PASS
ACCESSIBILITY_SMOKE=PASS
```

### Forms and integrations

```text
PREQUAL_FORM=PASS
CONTACT_FORM=PASS
CALLBACK_FORM=PASS
LENDER_PARTNER_FORM=PASS
REFERRAL_PARTNER_FORM=PASS
DEAL_INQUIRY_FORM=PASS
DUPLICATE_CLICK=PASS
IDEMPOTENCY_COLLISION=PASS
CONSENT_EVIDENCE=PASS
RATE_LIMIT=PASS
CODESRA_OUTBOX=PASS
CODESRA_INBOX=PASS
ODOO_SANDBOX_UPSERT=PASS
ODOO_DUPLICATE_DELIVERY=PASS
WEBHOOK_SIGNATURE=PASS
WEBHOOK_REPLAY=PASS
WEBHOOK_COLLISION=PASS
DEAD_LETTER_REQUEUE=PASS
```

### Infrastructure

```text
DNS=PASS
TLS=PASS
CADDY_OR_EDGE_CONFIG=PASS
CORS=PASS
SECURITY_HEADERS=PASS
POSTGRES_PRIVATE=PASS
REDIS_PRIVATE=PASS
FIREWALL=PASS
HEALTH=PASS
READY=PASS
VERSION_IDENTITY=PASS
MONITORING=PASS
ALERTING=PASS
BACKUP_RESTORE=PASS
ROLLBACK=PASS
RESTART_BEHAVIOR=PASS
```

## Staging deployment sequence

1. Reconcile PR #10 and PR #13 with their bases.
2. Run exact-head CI and obtain independent review.
3. Merge the consolidation PRs in dependency order.
4. Create and complete the focused backend and frontend feature PRs.
5. Regenerate and commit OpenAPI and typed clients.
6. Merge reviewed feature PRs into protected `release/staging`.
7. Build all images from the exact protected merged SHAs.
8. Generate SBOM, scans, provenance, signatures, and digests.
9. Inventory and approve the staging host.
10. Configure secrets outside Git.
11. Configure staging DNS, TLS, Caddy/edge routes, and Keycloak.
12. Back up the staging database or confirm an empty staging database.
13. Pull images by digest.
14. Run the one-time migration service.
15. Start API and workers with external delivery disabled.
16. Start marketing, borrower, lender, and admin portals.
17. Validate health, readiness, version identity, logs, metrics, and restart behavior.
18. Run browser E2E and form E2E.
19. Confirm forms create MoneyBee records and pending outbox events.
20. Confirm disabled delivery workers leave events pending.
21. Exercise rollback to the previous immutable release.
22. Record an explicit staging acceptance packet.
23. Only after separate approval, run one sandbox Codestra→Odoo canary.

## Production gate

Do not deploy production until all of the following are true:

```text
STAGING_ACCEPTANCE=PASS
INDEPENDENT_REVIEW=PASS
PROTECTED_MERGE=PASS
EXACT_MERGED_SHA_VERIFIED=YES
IMMUTABLE_IMAGES=YES
IMAGE_SIGNATURES=PASS
SBOM=PASS
VULNERABILITY_GATE=PASS
MIGRATION_REHEARSAL=PASS
BACKUP_RESTORE=PASS
KEYCLOAK_E2E=PASS
FORM_E2E=PASS
TENANT_ISOLATION=PASS
WEBHOOK_SECURITY=PASS
ODOO_SANDBOX_CANARY=PASS
ROLLBACK=PASS
PRODUCTION_CHANGE_APPROVAL=APPROVED
```

Even after a production web deployment, keep all live financial capabilities disabled until each capability receives its own provider-readiness, compliance, security, and operational approval.

## Required final Codex report

Codex must finish by posting an exact status record, not a general summary:

```text
BACKEND_SOURCE_SHA=
FRONTEND_SOURCE_SHA=
BACKEND_PR=
FRONTEND_PR=
BACKEND_CI=
FRONTEND_CI=
OPENAPI_SHA256=
BACKEND_IMAGE_DIGEST=
WORKER_IMAGE_DIGEST=
WEBHOOK_WORKER_IMAGE_DIGEST=
MARKETING_IMAGE_DIGEST=
BORROWER_IMAGE_DIGEST=
LENDER_IMAGE_DIGEST=
ADMIN_IMAGE_DIGEST=
SBOM=PASS|FAIL
SIGNATURE_VERIFICATION=PASS|FAIL
MIGRATION=PASS|FAIL
BACKUP_RESTORE=PASS|FAIL
KEYCLOAK_E2E=PASS|FAIL
FORM_E2E=PASS|FAIL
CODESRA_OUTBOX=PASS|FAIL
ODOO_SANDBOX_DELIVERY=PASS|FAIL|NOT_RUN
WEBHOOK_SECURITY=PASS|FAIL
STAGING_URLS=
STAGING_DEPLOYED=YES|NO
ROLLBACK_EXERCISED=YES|NO
PRODUCTION_DEPLOYED=NO
LIVE_CREDIT_PULL=DISABLED
LIVE_LENDER_SUBMISSION=DISABLED
LIVE_ESIGN=DISABLED
LIVE_FUNDING=DISABLED
LIVE_PAYMENTS=DISABLED
LIVE_PAYOUTS=DISABLED
LIVE_ODOO_WRITE=DISABLED
FINAL_STATUS=PASS|PARTIAL|BLOCKED
BLOCKERS=
```

Never report `PASS`, `READY`, `DEPLOYED`, or `LIVE` without direct evidence for the exact source SHA and artifact digest.