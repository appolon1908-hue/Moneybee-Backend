# MoneyBee Production Readiness Requirements

This document defines the additional features that must exist before MoneyBee can be considered production-ready. It supplements the backend implementation specification, build blueprint, and API contract.

## 1. Authentication and account security

Use the canonical Keycloak issuer `https://auth.codestra.co/realms/codestra`. Authentication factors and recovery are implemented through approved Keycloak flows; MoneyBee enforces application/tenant authorization.

Required:

- borrower, lender, employee/admin client separation;
- MFA policies appropriate to role and risk, with mandatory MFA for lender and MoneyBee privileged roles;
- password reset and account recovery with verified-channel, rate, replay, and audit controls;
- active session/device inventory, remote session revocation, refresh-token rotation, logout/revocation, idle and absolute timeouts;
- brute-force throttling, credential-stuffing detection, lockout/recovery policy, and security alerts;
- exact redirect/logout URI allowlists and PKCE S256;
- step-up authentication for sensitive PII, permissions, funding, commission, replay, and integration configuration;
- break-glass accounts that are tightly controlled, monitored, tested, and never used for routine work.

Do not enable unrestricted public identity-provider registration. Borrower onboarding should use a backend-issued, short-lived, single-use enrollment flow linked to the accepted lead/application. Lender and employee accounts require authorized provisioning/invitation.

Role templates:

```text
BORROWER
BORROWER_ADMIN
LENDER_ADMIN
LENDER_UNDERWRITER
LENDER_OPERATIONS
MONEYBEE_ADMIN
MONEYBEE_SALES
MONEYBEE_UNDERWRITER
MONEYBEE_COMPLIANCE
MONEYBEE_ACCOUNTING
MONEYBEE_SUPPORT
```

Backend permissions, resource ownership, tenant membership, assignment, and field-level policy remain authoritative.

## 2. Lead lifecycle and duplicate resolution

Lead lifecycle:

```text
NEW
CONTACTED
QUALIFIED
APPLICATION_STARTED
APPLICATION_COMPLETE
MATCHING
SUBMITTED
OFFERED
FUNDED
```

Alternate states:

```text
DUPLICATE
UNRESPONSIVE
DECLINED
WITHDRAWN
FRAUD_REVIEW
LOST
```

Every transition records actor/system, source/target state, reason, timestamp, request/trace ID, and resulting events.

Permanent attribution includes source, page, referrer, first/last touch, UTM fields, GCLID, FBCLID, affiliate, campaign, call-tracking ID, and session ID.

Duplicate detection is a versioned, explainable service distinct from HTTP idempotency. Signals may include normalized email, phone, EIN token/hash, legal/DBA name, business address, owner identity token, bank-account token, device, and existing CRM link. Sensitive raw identifiers are not copied into duplicate-search indexes.

A possible duplicate creates a review case with:

- candidate records and match reasons/confidence;
- fields and downstream records affected by a proposed merge;
- merge preview and conflict resolution;
- `MERGE`, `KEEP_SEPARATE`, and escalation outcomes;
- two-person approval for high-risk merges where configured;
- immutable audit and reversible linkage where legally/operationally feasible.

Merging must not erase consent evidence, attribution history, application history, lender submissions, offers, adverse actions, complaints, or audit data.

## 3. Fraud and risk-review engine

Create a dedicated, versioned fraud/risk subsystem. Signals may include:

- email and phone reputation/verification;
- IP reputation, proxy/VPN/Tor indicators;
- privacy-preserving device/session risk;
- application and submission velocity;
- repeated/linked applications;
- synthetic-identity indicators;
- business-owner, EIN, address, document, or bank-ownership mismatch;
- duplicate bank-account tokens;
- suspicious profile/address changes;
- document manipulation signals;
- webhook/provider anomalies.

Output:

```text
LOW_RISK
REVIEW_REQUIRED
BLOCKED
```

A result includes policy/model version, input-source references, reason codes, score bands where used, timestamps, expiry, and reviewer outcome. Do not expose vendor internals or use protected characteristics. Automated blocking must be narrowly defined and reviewable. Fraud status does not itself create a credit adverse action; downstream compliance policy determines required action/notice.

Provide a manual review queue, evidence access controls, false-positive resolution, override reason/approval, and full audit.

## 4. Application and requirements engine

The full application covers:

- legal name, DBA, EIN token, entity type, formation state/date, industry/NAICS, address, website, phone;
- amount, purpose, product preference, desired timing;
- annual/monthly revenue, deposits, balances, existing debt/positions, expenses;
- each required owner's name, ownership, title, address, DOB, phone, email, and tokenized identity information.

The requirements engine is authoritative for completion. It evaluates field presence, validation, owners/ownership totals, document states, bank status, KYB/KYC, credit authorization where applicable, fraud/manual review, consents, disclosures, and product/jurisdiction rules. Responses include completion percentage, requirement states, blockers, and next actions.

## 5. Bank-data subsystem

Manage connections, accounts, transaction/statement ingestion, consent, refresh, disconnection, access, and normalized cash-flow analysis.

Normalized fields include:

- average monthly deposits;
- average daily balance;
- negative-balance days;
- NSF count;
- deposit count;
- revenue and cash-flow trends;
- existing payment activity;
- risk flags;
- analysis period, completeness, data source, and version.

Raw provider data is minimized, encrypted, access-controlled, and retention-bound. Reanalysis is versioned. Bank ownership mismatch feeds risk review. The domain/matching engine consumes normalized MoneyBee data, not provider-specific payload structures.

## 6. KYB/KYC and identity

Separately track business verification, owner identity, TIN match, registration, address, sanctions/watchlist, fraud signals, and manual review.

Normalized outcome:

```text
VERIFIED
MANUAL_REVIEW
FAILED
```

Each check stores provider reference, type, version, observed time, expiry, reason codes, safe normalized result, reviewer, and audit. Access to identity source data is permissioned and logged.

## 7. Document processing

Supported categories include bank statements, tax returns, identity documents, business registration, voided checks, debt schedules, financial/ownership documents, contracts, and funding agreements.

Lifecycle:

```text
UPLOAD_AUTHORIZED
UPLOADED
QUARANTINED
MALWARE_SCANNING
TYPE_VALIDATION
CLASSIFICATION
OCR_EXTRACTION
HUMAN_REVIEW
APPROVED
REJECTED
EXPIRED
DELETED_PER_POLICY
```

Requirements:

- MIME/content inspection and signature/magic-byte validation; never trust extension alone;
- size/page limits, encryption, checksums, tenant/object-key isolation;
- malware scanning and quarantine before downstream access;
- OCR/extraction results stored separately with confidence and source location;
- human validation for low-confidence or sensitive extractions;
- immutable original, versioned derived artifacts, retention/legal hold;
- short-lived authorized downloads and access audit;
- protection against archive bombs, active content, path manipulation, and unsafe previews.

## 8. Underwriting policy and review

V1 uses rules + normalized financial/credit/KYB data + human review.

Every decision references an immutable policy version:

```text
policy_id
version
effective_from
effective_to
rules/artifact hash
input snapshot/hash
output
reason codes
reviewer
review time
override/approval
```

A policy change never silently changes the explanation of a historical decision. Re-evaluation creates a new review/version. Protected compliance/demographic data is excluded. Overrides require permission, structured reason, and approval where configured.

## 9. Lender programs and submissions

Programs are versioned/effective-dated and include amounts, monthly revenue, time in business, credit range, states, allowed/excluded industries, existing positions, bank/risk rules, and product configuration.

Matching sequence:

```text
program
state/jurisdiction
industry
revenue
time in business
authorized credit
bank analysis
existing debt/positions
product fit
risk/readiness
explainable score
```

Lender compensation is recorded separately and cannot be the undisclosed eligibility rule.

Every lender submission stores application, lender, program and their versions; consent/disclosure package version; idempotency key; external reference; timestamps; status; attempt/retry state; and minimum-necessary payload manifest.

States:

```text
QUEUED
SENT
RECEIVED
UNDER_REVIEW
CONDITIONS
OFFERED
DECLINED
FAILED
WITHDRAWN
```

Transitions are idempotent and audited. Portal/API adapters cannot create duplicate submissions from retries.

## 10. Offer, contract, funding, and commission lifecycle

Offers store lender/program, product, amount/currency, term, payment details, APR/factor where applicable, fees, total repayment, prepayment, guarantee, collateral, expiration, conditions, disclosure, status, and version.

Offer/deal lifecycle:

```text
DRAFT
AVAILABLE
ACCEPTED
CONDITIONS_PENDING
CONTRACTING
APPROVED_FOR_FUNDING
FUNDS_SENT
FUNDING_CONFIRMED
FUNDED
```

Alternates: `DECLINED`, `EXPIRED`, `WITHDRAWN`.

An accepted offer is not funded. E-sign tracks contract/template version, signer, signing order, signed time, provider envelope, immutable document hash, executed agreement, and webhook history.

Funding reconciliation records:

- approval, sent, expected settlement, confirmed and exception states;
- lender/bank/provider references;
- funded amount/date;
- reconciliation source/file/version;
- matched/unmatched/variance details;
- reviewer and resolution;
- idempotent CRM/application events.

Commission accounting records funded amount, percentage/flat basis, expected/received amounts, currency, lender/product, salesperson and affiliate splits, payment dates, outstanding/variance status, and reconciliation evidence. Corrections use journal-style adjustments, not destructive overwrites.

## 11. Compliance, complaints, renewals, and affiliates

Compliance engine inputs: applicant/business state, product, lender, transaction type, amount, and effective date. Outputs: required disclosures/consents, credit authorization, privacy/data-sharing notices, state requirements, adverse action, and retention.

Consent evidence stores type, immutable version/hash, accepted time, IP, user agent, actor/application, presentation/acceptance method, and withdrawal/supersession history.

Adverse action follows structured decision → reason codes → policy → notice generation → review → send → delivery → archive. Ordinary sales users cannot author arbitrary notices.

Restricted compliance data uses separate tables/keys and explicit permissions such as `compliance.restricted.read`; broad admin or sales roles do not inherit it automatically.

Complaint management stores borrower/application/lender, category, description, priority, owner, status, SLA, communications, partner escalation, resolution, opened/resolved dates, and audit. States: `OPEN`, `INVESTIGATING`, `WAITING_ON_PARTNER`, `ESCALATED`, `RESOLVED`.

Renewal engine tracks funded eligibility dates, policy version, refreshed-data requirements, review, CRM opportunity, consent-aware notification, and linkage to a new/refreshed application. It must not auto-submit or auto-pull data/credit without authority.

Affiliate management tracks affiliate identity/status, contract, approved campaign/creative, source/lead/application/funding linkage, revenue/payout, conversion, fraud/complaints, consent/source evidence, and suppression. Payouts are reconciled and auditable.

## 12. Reporting read models

Create definition-backed, permissioned read models:

- Marketing: leads, CPL, applications, offers, funded deals, cost/funded deal, volume, revenue, ROAS.
- Sales: new leads, contacts, application starts/completions, offers, funding, representative conversion.
- Lenders: sent applications, offer/approval rates, funded volume, average deal, turnaround.
- Finance: funded amount, expected/received/outstanding commission, revenue by lender/product/salesperson/source/page/affiliate.
- Risk/compliance: review queues, complaints/SLA, adverse-action delivery, consent/document exceptions—without protected data leakage.

Each metric returns definition/version, filters, currency/timezone, data-through timestamp, and source completeness. Exports enforce permissions, row limits, asynchronous generation, encryption, expiry, and audit.

## 13. Mandatory production gates

Production remains `NO_GO` until evidence confirms:

- authentication, mandatory privileged MFA, recovery/session controls;
- RBAC, tenant and field-level authorization tests;
- PII encryption/tokenization and access audit;
- consent/disclosure/adverse-action workflows;
- fraud controls and manual review;
- CRM retries, database leasing, idempotency, and DLQ/replay;
- lender-submission idempotency/isolation;
- document quarantine, malware/type checks, and safe access;
- underwriting/matching/program versioning and explanations;
- contract/funding/commission reconciliation;
- complaints and operational escalation;
- backup, point-in-time restore test, disaster recovery;
- monitoring/alerting and runbooks;
- penetration, dependency, secret, container, IaC, authorization, and tenant-isolation testing;
- immutable build, SBOM/provenance, staging synthetic journey, canary, and rollback rehearsal.

A checklist without automated tests, runtime evidence, owners, and runbooks does not satisfy a gate.
