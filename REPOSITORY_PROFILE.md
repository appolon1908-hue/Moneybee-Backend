# Repository Profile — `Moneybee-Backend`

## Identity

- **Repository:** `appolon1908-hue/Moneybee-Backend`
- **Category:** Product backend — business funding
- **Visibility:** `public`
- **Default branch:** `main`
- **Authority:** Primary MoneyBee backend and data authority
- **Status:** FastAPI/PostgreSQL platform with live credit, lender submission, e-sign, and funding capabilities explicitly gated.

## Purpose

Provides the MoneyBeeLoans server-side authority for borrowers, businesses, owners, applications, underwriting, matching, offers, documents, funding, commissions, consent, compliance, reporting, and integrations.

## Owns

- Versioned FastAPI/OpenAPI contracts and PostgreSQL system of record
- MoneyBee business rules, authorization, audit, idempotency, queues, retries, and dead letters
- Underwriting, matching, offers, documents, funding, compliance, and provider adapters

## Does not own

- Browser presentation
- CRM as the application database
- Unapproved live credit pulls, lender submissions, e-sign sends, or funding actions

## Key integrations

- `Moneybee-frontend-`
- Keycloak
- Middleware and Odoo
- Plaid, KYB/KYC, credit, e-sign, lender, email, SMS, and analytics adapters

## Current priorities

1. Complete the API v2 implementation ledger
2. Prove tenant isolation, command context, idempotency, concurrency, outbox, and inbox behavior
3. Finish provider translators, documents, and PII controls
4. Maintain capability freezes until legal, security, vendor, and launch gates pass

## Governance and safety

- Promotion model: `feature/docs/fix/security/upgrade -> development -> test -> staging -> production -> main`.
- Use pull requests and exact-head/merge-result validation; source merge never authorizes financial activation.
- Never commit credentials, borrower PII, credit data, documents, database dumps, or provider secrets.
- Production artifacts must be immutable and every external effect independently approved.
- This document does not enable credit pulls, lender submissions, e-sign, funding, or production deployment.

## Account-wide catalog

See `appolon1908-hue/documentaions/REPOSITORY_CATALOG.md`.
