# MoneyBee product/API authority matrix

Updated: 2026-09-01

This matrix maps the product flows implemented by the MoneyBee repositories to their canonical backend authority. The generated endpoint catalog remains the exhaustive route inventory; it currently contains 189 canonical `/api/v2` endpoints. This document explains how the major flows fit together and which layer is allowed to make each decision.

## Contract boundary

- Canonical API prefix: `/api/v2`.
- `/api/v1` is a hidden compatibility alias and is not a frontend development target.
- The backend owns identity resolution, permissions, state transitions, money calculations, disclosure text, persistence, audit evidence, idempotency, and external-delivery gates.
- The frontend owns presentation, accessible interaction, local form state, cancellation of obsolete reads, and display of backend-provided values.
- A disabled or unconfigured provider is an explicit unavailable capability, never an implied success.

## Product flow matrix

| Product flow | Primary frontend surface | Canonical endpoint(s) | Backend authority | Idempotency / concurrency | Implementation state |
| --- | --- | --- | --- | --- | --- |
| Session and active organization | All authenticated portals | `GET /auth/context`, `GET /me`, `GET /me/capabilities`, `GET /portal/navigation` | OIDC token verification, local principal, memberships, permissions, tenant context | Session refresh is centralized by the frontend client; authorization is repeated server-side | Implemented |
| Public prequalification | Marketing site | `POST /public/prequalifications` | Validation, consent evidence, lead creation, request correlation, durable CRM/outbox intent | `Idempotency-Key` is required; same payload replays, different payload conflicts | Implemented |
| Public contact and partner intake | Marketing site | `POST /public/contact-requests`, `POST /public/callback-requests`, `POST /public/lender-partner-inquiries`, `POST /public/referral-partner-inquiries`, `POST /public/deal-submission-inquiries` | Validation, anti-abuse controls, durable intake and integration evidence | Public write idempotency and rate limits | Implemented |
| Application creation and resume | Borrower portal | `POST /applications`, `POST /applications/from-lead/{lead_id}`, `GET /applications`, `GET /applications/{application_id}` | Application identity, borrower ownership, status and version | Database constraints and authorized resource lookup | Implemented |
| Business and applicant data | Borrower portal | `PUT /applications/{application_id}/business`, `PUT /applications/{application_id}/financial-profile`, owner collection/item endpoints | Canonical application data, validation, tenant ownership | Server-side authorization and transaction boundaries | Implemented |
| Application completion | Borrower portal | `GET /applications/{application_id}/requirements`, `GET /applications/{application_id}/timeline`, `POST /applications/{application_id}/submit` | Required-section calculation and legal state transition | Submission is transition-guarded; mutation safety is backend-owned | Implemented |
| Documents and upload sessions | Borrower portal | Borrower application document and upload-session endpoints | Document metadata, checksums, malware-scan state and object-storage capability | Upload completion is explicit; provider capability fails closed | Implemented; provider activation separate |
| Bank connection and analysis | Borrower and lender portals | `/applications/{application_id}/bank/link-session`, `/bank/exchange`, `/bank/sync`, `/bank/accounts`, `/bank/analysis`; lender bank review endpoints | Plaid/provider adapter selection, encrypted credential references, normalized accounts/transactions/analysis | Capability `bank.live_connection`; durable webhook replay handling | Implemented; live provider disabled by default |
| Matching | Borrower/admin | `POST /applications/{application_id}/match`, admin matched-submission preparation | Versioned lender-program rules, eligibility score and reasons | Existing matches are replaced in one transaction; application transition is guarded | Implemented |
| Lender programs | Lender/admin | Lender program collection/item endpoints and admin catalog | Program limits, states, industries, activation and version | Optimistic/versioned program logic where supported | Implemented |
| Lender work queue | Lender portal | `GET /lender/workspace`, `GET /lender/submissions`, `GET /lender/submissions/{submission_id}/workspace`, assignment endpoint | Lender membership, submission visibility and assignment | Tenant and lender authorization on every read/write | Implemented |
| Conditions | Borrower and lender portals | Borrower application condition list/submit; lender create/approve/reject/waive endpoints | Condition status, evidence and permitted actor transition | Row/state guards prevent invalid or repeated decisions | Implemented |
| Underwriting decisions | Lender/admin | Lender decision endpoint and `POST /admin/applications/{application_id}/underwriting/reviews` | Decision, reason codes, policy evidence and application transition | Authorized decision actor; immutable review evidence | Implemented |
| Offers | Borrower and lender portals | Lender offer creation; `GET /applications/{application_id}/offers`; `POST /offers/{offer_id}/accept` | Amount, term, payment schedule, APR/factor-rate fields, availability and acceptance transition | Acceptance uses server state/version and mutation protection | Implemented |
| Commercial-financing disclosure | Borrower/admin | `GET /borrower/offers/{offer_id}/commercial-financing-disclosure`; borrower/admin acknowledgment endpoints; admin compliance list | Immutable calculated disclosure record and exact disclosure text | Acknowledgment requires `Idempotency-Key`, row lock, authenticated actor and audit event | Implemented in this branch |
| Contracts and e-sign evidence | Borrower/admin | Contract collection/detail/signature/void operations in the generated catalog | Contract status, document evidence and provider capability | Live e-sign send remains fail closed until provider readiness | Implemented; live send disabled by default |
| Funding | Borrower/lender/admin | Application funding read; lender/admin funding lifecycle endpoints | Approved amount, funded amount, lifecycle transition and audit evidence | State transition guards; external money movement remains capability-gated | Implemented; live movement not activated |
| Double-entry finance | Admin | `/finance/accounts`, `/finance/periods`, `/finance/journal-entries`, journal postings and trial balance | Decimal money, balanced postings, accounting period controls | Journal idempotency and transaction checks; close/post operations are controlled | Implemented |
| Commissions | Admin | Commission collection, receipt, split and adjustment endpoints | Expected/received amounts, recipient splits and adjustments | Ledger/commission operations are transactional and audited | Implemented |
| Commission tax evidence | Admin compliance | Compliance tax-record list, generate, TIN and filing-evidence endpoints | Tax-year aggregation, encrypted write-only TIN, 1099 threshold flag and filing evidence | Generation and filing evidence use idempotency; filing reference cannot be silently replaced | Implemented in this branch; no tax filing is transmitted |
| Adverse-action notices | Admin compliance | Application-specific notices plus global paginated compliance list | Regulation-B notice snapshot, creditor, principal reasons and status | Generated record is preserved; delivery is a separate capability-controlled concern | Implemented in this branch |
| Compliance overview | Admin compliance | `GET /admin/compliance/overview` | Counts of records requiring acknowledgment, delivery evidence, TIN or filing attention | Read-only aggregate from authoritative records | Implemented in this branch |
| Tasks, notifications and conversations | Borrower/lender/admin portals | Portal-specific task, notification, conversation and message endpoints | Visibility, assignment, unread state and message persistence | Tenant/permission checks; external email/SMS remains independently gated | Implemented |
| CRM and integration operations | Admin | CRM deliveries/events, integration inbox/events/control plane and operational exceptions | Durable inbox/outbox state, retries, failures and recovery evidence | Requeue commands are explicit and idempotent where applicable | Implemented; external delivery disabled by default |
| Provider webhooks | Integration edge | Lender, payment, Plaid and other approved webhook endpoints in the generated catalog | HMAC/token verification, timestamp/body limits, replay detection and durable receipt | Payload-hash deduplication and durable inbox processing | Implemented; provider configuration required |
| Audit and readiness | Admin/operations | Audit-event, system-readiness, health and capability endpoints | Exact actor/action/resource evidence and fail-closed readiness | Read-only checks; no health endpoint enables a provider | Implemented |

## New compliance API response rules

The new global compliance collections use a consistent page envelope:

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

Tax-record responses expose `tin_present`; they never expose plaintext TINs or encrypted ciphertext. Disclosure acknowledgment ignores client-supplied actor fields and records the authenticated subject.

## Completion boundary

Repository implementation and CI validation do not activate a provider, transmit email or SMS, submit a lender application, file a tax form, or move money. Those actions require separate staging evidence, approved secrets, capability activation, rollback evidence and production authorization.
