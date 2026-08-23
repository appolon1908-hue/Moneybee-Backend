# MoneyBee V1 API Contract

Contract version: `v1`  
Base URL: `https://api.moneybeeloans.com/api/v1`  
Canonical OIDC issuer: `https://auth.codestra.co/realms/codestra`

The backend repository owns the generated OpenAPI document. The frontend repository pins a reviewed copy or generated client to the same contract version. CI must fail on unreviewed breaking changes or generated-client drift.

## Protocol conventions

- HTTPS and JSON; document upload bytes use signed object-storage URLs.
- Authenticated calls use `Authorization: Bearer <access-token>`.
- Human tokens come from Authorization Code + PKCE S256. Machine tokens use Client Credentials.
- Mutations that could duplicate work accept `Idempotency-Key`.
- Clients send/propagate `X-Request-ID`; the server returns the effective request ID.
- Timestamps are RFC 3339 UTC. Money uses decimal strings and ISO 4217 currency.
- List endpoints use opaque cursor pagination and bounded page sizes.
- Errors use `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`, `request_id`, and optional field `errors`.
- `401` means reauthenticate; `403` means authenticated but forbidden; `409` represents state/version conflict; `422` is validation; `429` includes retry guidance.
- Unknown fields are rejected for sensitive/mutating schemas unless a compatibility policy explicitly permits them.
- IDs are opaque UUID/ULID strings. Clients never derive meaning from them.
- Sensitive responses are `Cache-Control: no-store`.

## Public prequalification

### `POST /public/prequalifications`

Example request:

```json
{
  "funding_amount": "75000.00",
  "currency": "USD",
  "use_of_funds": "WORKING_CAPITAL",
  "time_in_business_months": 36,
  "monthly_revenue": "85000.00",
  "business_name": "ABC Trucking LLC",
  "first_name": "John",
  "last_name": "Smith",
  "email": "john@example.com",
  "phone": "+15555555555",
  "postal_code": "33101",
  "consents": [
    {
      "type": "ELECTRONIC_COMMUNICATIONS",
      "document_version": "2026-08-23",
      "accepted": true
    }
  ],
  "marketing": {
    "landing_page": "trucking-business-loans",
    "original_referrer": "https://www.google.com/",
    "referrer": "https://www.google.com/",
    "utm_source": "google",
    "utm_medium": "cpc",
    "utm_campaign": "trucking-loans",
    "utm_content": null,
    "utm_term": "truck business financing",
    "gclid": null,
    "fbclid": null,
    "affiliate": null,
    "call_tracking_id": null
  },
  "anti_bot_token": "provider-token"
}
```

Success is `202 Accepted` with a stable reference, not an approval claim:

```json
{
  "lead_id": "01J...",
  "reference": "MB-108942",
  "status": "RECEIVED",
  "next_action": {
    "type": "CREATE_ACCOUNT",
    "url": "https://app.moneybeeloans.com/start/01J..."
  },
  "request_id": "01J..."
}
```

Backend side effects are transactional lead/business/attribution/consent/outbox persistence followed by asynchronous routing, Codestra middleware/CRM delivery, and approved communications.

## Identity

- `GET /me`
- `GET /me/permissions`

`/me` returns internal user ID, display data, tenant memberships, active context, and safe profile fields. `/me/permissions` returns effective permission identifiers for the active context. Neither endpoint returns secrets or unrestricted PII.

## Borrower applications

- `POST /applications`
- `GET /applications/{application_id}`
- `PATCH /applications/{application_id}`
- `POST /applications/{application_id}/submit`
- `GET /applications/{application_id}/status`
- `GET /applications/{application_id}/requirements`
- `GET /applications/{application_id}/business`
- `PUT /applications/{application_id}/business`
- `GET /applications/{application_id}/owners`
- `POST /applications/{application_id}/owners`
- `PATCH /applications/{application_id}/owners/{owner_id}`

PATCH/update requests include a record `version` or `If-Match` value. Conflicts return `409` with current version and safe recovery guidance. Submission validates authoritative requirements and returns the resulting status/next action.

Owner identifiers are collected using an approved tokenization/hosted-field contract. Read models expose only masked values and status.

## Documents

- `POST /applications/{application_id}/documents/upload-session`
- `GET /applications/{application_id}/documents`
- `GET /documents/{document_id}`
- `DELETE /documents/{document_id}`
- `POST /documents/{document_id}/classify`
- `POST /documents/{document_id}/verify`

Upload-session requests declare expected category, MIME type, size, and checksum. Responses return a short-lived upload target plus document ID and required headers. A document is unavailable to downstream users until upload completion and security scanning succeed. Downloads use short-lived authorized URLs or streamed responses and create access-audit events.

## Banking

- `POST /banking/link-token`
- `POST /banking/exchange`
- `GET /applications/{application_id}/bank-analysis`
- `POST /webhooks/plaid`

Link-token creation is tied to the authenticated borrower/application. Exchange sends the provider public token only to the backend. Webhooks require provider verification, replay protection, event idempotency, and asynchronous processing.

## Lenders and programs

- `GET /lenders` — scoped/authorized list
- `POST /admin/lenders`
- `GET /lenders/{lender_id}`
- `PATCH /admin/lenders/{lender_id}`
- `GET /lenders/{lender_id}/programs`
- `POST /lenders/{lender_id}/programs`
- `PATCH /lender-programs/{program_id}`

Program mutations include effective dates and versioned rule definitions. Responses never expose another lender's private configuration outside permitted admin context.

Lender inbox/read endpoints use a protected lender namespace:

- `GET /lender/applications`
- `GET /lender/applications/{application_id}`
- `GET /lender/applications/{application_id}/documents`
- `POST /lender/applications/{application_id}/conditions`
- `POST /lender/applications/{application_id}/decline`

All enforce lender assignment/submission, tenant membership, user permissions, and field-level authorization.

## Matching and lender submission

- `POST /applications/{application_id}/match`
- `GET /applications/{application_id}/matches`
- `POST /applications/{application_id}/submit-to-lender`
- `POST /applications/{application_id}/submit-to-lenders`

Match results include eligibility, score, explainable components/reasons, program/rule version, missing requirements, and creation/expiration timestamps. Compensation is never the undisclosed sole ranking input.

Submission requests identify exact match/program versions, required consent/disclosure state, and selected lenders. They are idempotent and produce lender-submission and integration events.

## Offers

- `GET /applications/{application_id}/offers`
- `POST /lender/applications/{application_id}/offers`
- `GET /offers/{offer_id}`
- `POST /offers/{offer_id}/accept`
- `POST /offers/{offer_id}/decline`
- `POST /offers/{offer_id}/expire`

Offer representations include amount/currency, product, term, payment frequency, estimated payment, APR and/or factor where applicable, origination/other fees, total repayment, prepayment terms, collateral, guarantee, conditions, expiration, status, and disclosure version. Acceptance requires expected offer version, required disclosure acceptance, consent evidence, and an idempotency key.

## Underwriting

- `GET /applications/{application_id}/underwriting`
- `POST /applications/{application_id}/underwriting/review`
- `POST /applications/{application_id}/conditions`
- `POST /applications/{application_id}/decision`

V1 supports rules, normalized data, and human review. Decision requests require permission, reason codes, version, and required compliance workflow. Protected Section 1071/demographic data must not appear in underwriting or matching responses.

## Admin leads and operations

- `GET /admin/leads`
- `GET /admin/leads/{lead_id}`
- `PATCH /admin/leads/{lead_id}`
- `POST /admin/leads/{lead_id}/assign`
- `POST /admin/leads/{lead_id}/convert`
- `GET /admin/integrations/health`
- `GET /admin/webhook-events`
- `GET /admin/audit-events`

List filtering, sort fields, and exports are allowlisted. Admin scope does not bypass tenant, PII, credit, 1071, or document permissions.

## CRM and Codestra middleware

- `GET /admin/crm/events`
- `POST /admin/crm/events/{event_id}/retry`
- `GET /admin/crm/mappings`
- `PUT /admin/crm/mappings`
- `POST /webhooks/crm`

Outbound event records expose sanitized delivery metadata: event ID/type/version, idempotency key, status, attempt count, timestamps, response code/category, next retry, and trace ID. Raw secrets and sensitive provider responses are never returned.

Inbound CRM webhooks support versioned events:

- `LeadAssigned`
- `LeadContacted`
- `ApplicationRequested`
- `ApplicationReceived`
- `DocumentsRequested`
- `OfferReceived`
- `OfferAccepted`
- `Declined`
- `Funded`
- `Lost`

The receiver verifies authentication/signature, timestamp/replay window, event ID, provider/tenant, schema, and transition. Accepted delivery does not mean every business transition succeeded; processing status is observable by authorized admins.

## Communications

- `POST /communications/email`
- `POST /communications/sms`
- `GET /applications/{application_id}/communications`

Initial templates: Lead Received, Complete Your Application, Documents Needed, Application Complete, Offer Available, Offer Expiring, Contract Ready, Funding Approved, Funds Sent, Renewal Eligible.

Every send enforces template version, purpose/consent/suppression policy, authorized recipient, idempotency, provider delivery tracking, and audit. Clients do not submit arbitrary provider credentials or unrestricted HTML.

## Contract governance

- Backend CI generates and validates `openapi/moneybee-v1.json`.
- Frontend CI regenerates or validates the typed API client from that artifact.
- Breaking changes require a new version or documented compatibility window.
- Schemas include examples and security/permission metadata.
- Consumer-driven tests cover all four frontend applications.
- Webhook payloads are independently versioned and retained for replay compatibility.
- Contract tests include tenant isolation, masked PII, unsupported transitions, stale versions, idempotency, duplicate webhooks, provider outage, and retry/DLQ behavior.


## Expanded V1 feature surface

The implementation blueprint adds the following explicit operations. These remain subject to the same authentication, tenant, permission, version, idempotency, PII, and problem-detail rules above.

### Borrower dashboard, timeline, owners, contracts, funding, and messages

- `GET /client/dashboard`
- `GET /applications/{application_id}/timeline`
- `DELETE /applications/{application_id}/owners/{owner_id}`
- `GET /applications/{application_id}/contracts`
- `GET /applications/{application_id}/funding`
- `GET /applications/{application_id}/messages`

The dashboard is an aggregate read model with current application, completion, next action, requirements summary, recent messages, offers/contracts/funding summary, and stale-data timestamp. It does not create an independent source of truth.

### Business verification

- `POST /applications/{application_id}/business-verification`
- `GET /applications/{application_id}/business-verification`
- `POST /webhooks/kyb`

Normalized verification includes status, business-registration match, tax-ID match, address match, watchlist result, risk flags, review state, provider reference, and observed timestamp. Responses mask identifiers and exclude raw provider payloads.

### Lender workspace

- `GET /lender/dashboard`
- `POST /lender/applications/{application_id}/decision`
- `GET /lender/offers`
- `GET /lender/fundings`
- `GET /lender/programs`

A lender can access only applications explicitly submitted to that lender. Decision and condition operations require a current submission, permission, expected version, approved reason codes, and audit evidence.

### Administrative dashboards and lead merge

- `GET /admin/dashboard`
- `GET /admin/pipeline`
- `GET /admin/funnel`
- `GET /admin/funding-summary`
- `GET /admin/marketing-performance`
- `POST /admin/leads/{lead_id}/merge`
- `GET /admin/crm/events/{event_id}`
- `POST /admin/crm/events/{event_id}/replay`
- `GET /admin/audit-events/{event_id}`

Dashboard values are backend-defined read models with metric definition, data-through timestamp, currency/timezone, filter context, and permissions. Lead merge requires source/target validation, duplicate evidence, preview, reason, idempotency, and an immutable audit record.

### Compliance, disclosures, consent, and adverse action

- `GET /applications/{application_id}/required-disclosures`
- `POST /applications/{application_id}/consents`
- `GET /applications/{application_id}/consents`
- `POST /applications/{application_id}/adverse-action`
- `GET /applications/{application_id}/adverse-action`

Required-disclosure responses identify product, jurisdiction, lender/context, immutable version/hash, effective date, presentation instructions, and acceptance requirements. Consent creation records exact document/disclosure version, text/artifact hash, time, actor, IP, user agent, request ID, and method. Adverse-action creation accepts approved structured reason codes and workflow metadata, never unrestricted denial prose from ordinary sales users.

### Provider webhooks

- `POST /webhooks/banking`
- `POST /webhooks/lenders`
- `POST /webhooks/esign`

Every provider webhook uses provider-specific verification, timestamp/replay protection, unique event ID, schema version, bounded body size, sanitized logging, durable receipt, and idempotent asynchronous processing. A `2xx` acknowledges durable receipt; downstream business processing remains observable separately.

### Health

- `GET /health/live`
- `GET /health/ready`

Liveness does not probe remote dependencies. Readiness checks only dependencies required to serve traffic, migration compatibility, and critical configuration with strict timeouts. Public health responses expose no connection strings, host inventory, secrets, tenant data, or raw dependency errors.


## Production-readiness API surface

The following operations support the mandatory security, risk, reconciliation, complaint, renewal, affiliate, and reporting workflows.

### Sessions and account security

- `GET /me/sessions`
- `DELETE /me/sessions/{session_id}`
- `POST /me/step-up/challenge`
- `GET /me/security-events`

Password reset, MFA enrollment/challenge, and identity-provider recovery execute through approved Keycloak OIDC/action flows rather than accepting passwords through MoneyBee API endpoints. MoneyBee session responses expose a safe device label, approximate location where permitted, created/last-active time, current-session marker, and revocable session ID—never tokens.

### Duplicate-review cases

- `GET /admin/duplicates`
- `GET /admin/duplicates/{case_id}`
- `POST /admin/duplicates/{case_id}/preview-merge`
- `POST /admin/duplicates/{case_id}/merge`
- `POST /admin/duplicates/{case_id}/keep-separate`
- `POST /admin/duplicates/{case_id}/escalate`

Decisions require expected case version, structured reason, idempotency key, and permission. Merge preview identifies conflicts and affected object types without exposing unauthorized fields. Historical consent, attribution, lender, offer, adverse-action, complaint, and audit records remain preserved.

### Fraud/manual review

- `GET /admin/fraud-reviews`
- `GET /admin/fraud-reviews/{review_id}`
- `POST /admin/fraud-reviews/{review_id}/request-information`
- `POST /admin/fraud-reviews/{review_id}/clear`
- `POST /admin/fraud-reviews/{review_id}/block`
- `POST /admin/fraud-reviews/{review_id}/escalate`
- `POST /admin/fraud-reviews/{review_id}/override`

Responses use safe reason categories and evidence references. They do not reveal exploitable vendor rules to borrowers or unauthorized staff. Override operations require step-up authentication, structured reason, and configured approval.

### Document processing

- `GET /documents/{document_id}/processing`
- `GET /documents/{document_id}/versions`
- `GET /admin/documents/{document_id}/extractions`
- `POST /admin/documents/{document_id}/extractions/{extraction_id}/verify`
- `POST /admin/documents/{document_id}/reject`

Processing status is server-owned and may include quarantine, malware scan, type validation, classification, OCR/extraction, review, approval/rejection, and replacement requirement. Authorized extraction responses include value, confidence, source location, version, and verification status. Untrusted documents are never served inline.

### Underwriting policies and reviews

- `GET /admin/underwriting/policies`
- `POST /admin/underwriting/policies`
- `GET /admin/underwriting/policies/{policy_id}/versions`
- `POST /admin/underwriting/policies/{policy_id}/versions`
- `POST /applications/{application_id}/underwriting/re-evaluate`

Policy versions are immutable once effective. Decisions reference exact policy, input snapshot/hash, reason codes, reviewer, and override/approval evidence. Re-evaluation creates a new review; it does not rewrite history.

### Lender submissions

- `GET /applications/{application_id}/lender-submissions`
- `GET /lender/submissions/{submission_id}`
- `POST /lender/submissions/{submission_id}/withdraw`
- `GET /admin/lender-submissions`
- `GET /admin/lender-submissions/{submission_id}`
- `POST /admin/lender-submissions/{submission_id}/retry`

Submission responses include lender/program/application versions, external reference, status, timestamps, safe delivery state, and history. Create/retry/withdraw operations are idempotent. Lender users can access only their own submissions.

### Offer updates, contracts, and e-sign

- `PATCH /lender/offers/{offer_id}`
- `POST /lender/offers/{offer_id}/withdraw`
- `GET /contracts/{contract_id}`
- `POST /applications/{application_id}/contracts`
- `POST /contracts/{contract_id}/send`
- `GET /contracts/{contract_id}/signing-session`
- `POST /webhooks/esign`

Contract creation references accepted offer/disclosure versions. Send/signing-session operations require authorized signer state and idempotency. Executed agreements are immutable, hashed, access-controlled documents. Webhooks are verified, replay-protected, durably received, and processed asynchronously.

### Funding reconciliation and commissions

- `GET /applications/{application_id}/funding`
- `POST /admin/fundings/{funding_id}/mark-sent`
- `POST /admin/fundings/{funding_id}/confirm`
- `GET /admin/funding-reconciliations`
- `GET /admin/funding-reconciliations/{case_id}`
- `POST /admin/funding-reconciliations/{case_id}/resolve`
- `GET /admin/commissions`
- `GET /admin/commissions/{commission_id}`
- `POST /admin/commissions/{commission_id}/record-receipt`
- `POST /admin/commissions/{commission_id}/adjustments`

Offer acceptance never implies funding. Funding and commission commands require expected version, evidence/provider reference, idempotency, permission/step-up, and audit. Financial corrections are additive adjustments; historical amounts are not silently overwritten.

### Complaints

- `POST /complaints`
- `GET /complaints/{complaint_id}` — borrower-visible own complaint
- `GET /admin/complaints`
- `GET /admin/complaints/{complaint_id}`
- `PATCH /admin/complaints/{complaint_id}`
- `POST /admin/complaints/{complaint_id}/assign`
- `POST /admin/complaints/{complaint_id}/escalate`
- `POST /admin/complaints/{complaint_id}/resolve`

Complaint records include category, priority, borrower/application/lender linkage, SLA, owner, state, communications, resolution, and audit. Free-form text is treated as sensitive and protected from logging/analytics.

### Renewals

- `GET /applications/{application_id}/renewal-eligibility`
- `POST /applications/{application_id}/renewals`
- `GET /admin/renewals`
- `POST /admin/renewals/{renewal_id}/review`
- `POST /admin/renewals/{renewal_id}/notify`

Renewal eligibility is policy/version driven. Creating a renewal produces a linked new/refreshed application. Notification, bank refresh, credit access, and lender submission require their own current authority/consent; none is implied by prior funding.

### Affiliates

- `GET /admin/affiliates`
- `POST /admin/affiliates`
- `GET /admin/affiliates/{affiliate_id}`
- `PATCH /admin/affiliates/{affiliate_id}`
- `GET /admin/affiliates/{affiliate_id}/performance`
- `GET /admin/affiliate-payouts`
- `POST /admin/affiliate-payouts/{payout_id}/reconcile`

Affiliate records include status, contract/reference, approved campaigns/creative, attributed lead/application/funding, payout, fraud, conversion, complaint, and source/consent evidence. Partner-facing access, if added, requires a separate scoped tenant/API contract.

### Reporting

- `GET /admin/reports/marketing`
- `GET /admin/reports/sales`
- `GET /admin/reports/lenders`
- `GET /admin/reports/finance`
- `POST /admin/reports/exports`
- `GET /admin/reports/exports/{export_id}`

Report responses include metric-definition/version, active filters, currency/timezone, data-through time, and source completeness. Exports are permissioned, bounded, generated asynchronously, encrypted, short-lived, and audited.
