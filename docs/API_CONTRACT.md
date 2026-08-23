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
