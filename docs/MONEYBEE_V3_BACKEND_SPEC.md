# MoneyBee V3 Backend Specification

This document applies the V3 marketplace architecture to the dedicated backend repository. It separates implemented foundation work from required follow-up modules.

## Authority and security

FastAPI and PostgreSQL are the system of record. Frontends and the CRM never own underwriting, fraud, eligibility, offer normalization, commission, funding, or compliance decisions.

- API: `https://api.moneybeeloan.com/api/v1`
- Identity: `https://auth.codestra.co/realms/codestra`
- Human access: Authorization Code + PKCE
- Machine access: short-lived Client Credentials tokens
- PostgreSQL and Redis remain on a private Docker network
- Secrets stay server-side
- Financial mutations require authorization, idempotency, audit, and immutable events
- Protected characteristics must not be used for fraud or eligibility decisions

## Target module layout

Each domain module owns `models.py`, `schemas.py`, `repository.py`, `service.py`, and `router.py`.

Target domains: leads, applications, businesses, owners, requirements, documents, banking, verification, fraud, credit, lenders, lender programs, matching, underwriting, conditions, offers, contracts, funding, commissions, renewals, communications, CRM, compliance, complaints, affiliates, reporting, and users.

Provider implementations live behind interfaces for CRM, banking, KYB/KYC, credit, lenders, e-sign, email, and SMS. Workers own outbox delivery, communications, lender/CRM synchronization, reconciliation, and renewals.

## Core engines

### Requirements and resumability

The backend returns application completion, individual requirement states, and a structured next action. Business, financial profile, owners, documents, and other sections save independently with optimistic concurrency.

### Banking normalization

Provider payloads are normalized into bank connections, accounts, and analyses. Matching consumes authoritative values such as average monthly deposits, average daily balance, negative-balance days, NSF count, cash-flow trend, and existing obligations. Raw provider JSON is not the rules contract.

### Fraud

Fraud assessment can evaluate duplicate identifiers, duplicate bank accounts or owners, email/phone/IP/device velocity, business/bank/document/identity mismatch, repeated declines, and suspicious profile changes. It returns a decision, score, and explainable flags for operations review.

### Lender programs and matching

Programs are versioned with effective dates and immutable historical versions. A lender submission stores the exact version evaluated. Matching separates binary eligibility from fit ranking and returns specific reasons.

### Conditions and offers

Conditions move through `OPEN`, `BORROWER_ACTION_REQUIRED`, `SUBMITTED`, `UNDER_REVIEW`, `SATISFIED`, `REJECTED`, or `WAIVED`.

Offer comparison is normalized by the backend: amount, term, frequency, payment, APR or factor rate, fees, total repayment, prepayment terms, guarantee, and collateral. Vue does not calculate authoritative comparisons.

### Funding, commissions, and renewals

Offer acceptance is not funding. The lifecycle is accepted offer → pending/completed conditions → contract ready/signed → approved for funding → funds sent → funded → commission expected/received.

Commissions track base amounts, splits, adjustments, received amounts, differences, clawbacks, and payment dates. A renewal worker evaluates funded accounts and creates renewal opportunities, CRM tasks, and consent-aware notifications.

## API contract target

Public and identity:

- `POST /public/prequalifications`
- `PATCH /public/prequalifications/{lead_id}`
- `GET /public/products`
- `GET /me`, `GET /me/permissions`, `GET /me/sessions`

Applications:

- `POST /applications/from-lead/{lead_id}`
- `GET /applications/{id}`, `GET /applications/{id}/timeline`
- `GET /applications/{id}/requirements`
- `PUT /applications/{id}/business`, `PUT /applications/{id}/financial-profile`
- owner CRUD and `POST /applications/{id}/submit`

Banking, documents, and risk:

- bank link-token/exchange/accounts/analysis plus signed provider webhooks
- document upload sessions, metadata, download authorization, and deletion
- business verification, identity verification, credit, and fraud assessment

Marketplace:

- run/list matches
- lender submissions, decisions, conditions, and offers
- offer list/comparison/accept/decline
- condition completion/document/approve/reject
- funding status, confirmation, and reconciliation

Operations:

- integration inventory/events/retry/replay
- disclosures, consents, adverse action, and complaints
- admin leads, applications, lenders/programs, fundings, commissions, fraud/compliance review, audit, reporting, and reconciliation

## Database target

- Identity: users, organizations, memberships, roles, permissions
- Acquisition: leads, attribution, duplicates, assignments
- Applications: applications, history, businesses, addresses, owners, financial profiles
- Banking: connections, accounts, analyses
- Risk: business/identity verification, credit requests/results, fraud assessments/flags
- Documents: documents, requirements, extraction, review
- Lenders: lenders/users, programs, versions, rules
- Marketplace: matches, submissions, conditions, offers
- Funding: contracts, fundings, commissions/splits/adjustments, renewals
- Compliance: consents, versioned disclosures/acceptances, adverse actions, complaints
- Communications: messages, templates, preferences
- Integrations: CRM links, integration/webhook/outbox events, reconciliation
- Security: immutable audit events, idempotency keys, login events

Authoritative money uses `NUMERIC(18,2)`, never floating point. IDs use UUID, timestamps use timezone-aware values, variable evidence uses JSONB on PostgreSQL, and audited records carry actor/version data.

## Reliability

Commands such as lender submission, offer acceptance, contract creation, funding confirmation, commission posting, and CRM opportunity creation require idempotency records containing actor, endpoint, request hash, stored response, and expiry.

The same database transaction that changes state writes an outbox event. Workers lease records, retry with backoff, dead-letter exhausted work, and support controlled replay. External delivery never occurs between a database commit and an untracked network call.

## Current implementation status

Implemented now: FastAPI/OpenAPI, foundational models, public intake/consent/attribution, resumable application basics, dynamic requirement response, explainable matching, lender programs, offers, accepted-offer outbox event, admin metrics, Keycloak JWT enforcement, audit/outbox foundations, async PostgreSQL/SQLite, initial Alembic migration, Docker/Compose, and CI.

Not yet complete: the full modular refactor, remaining target tables/endpoints, real provider adapters, object storage and malware scanning, full idempotency persistence, contracts/e-sign, funding/commission/renewal engines, complete RBAC tests, backup/restore evidence, and production deployment.
