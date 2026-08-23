# MoneyBee Backend

Authoritative Python/FastAPI backend for **MoneyBeeLoans** — “Business funding that keeps you moving.”

## Repository ownership

This repository owns:

- FastAPI application and OpenAPI contract
- PostgreSQL system of record and Alembic migrations
- Redis caching, queues, workers, idempotency, retry, and dead-letter handling
- Authentication/authorization enforcement and audit trails
- Leads, applications, borrowers, businesses, owners, lenders, programs, matching, underwriting, offers, documents, funding, commissions, reporting, consent, and compliance
- CRM and Codestra middleware delivery
- Plaid, KYB/KYC, credit, e-sign, email, SMS, lender, and analytics adapters
- Docker, CI/CD, observability, security controls, and deployment configuration

The backend is the authority for business rules and data. The CRM is a sales system, not the application database. Frontend applications must communicate only through versioned APIs.

## Canonical boundaries

- Public API: `https://api.moneybeeloan.com/api/v1`
- Identity issuer: `https://auth.codestra.co/realms/codestra`
- Human authentication: Authorization Code + PKCE
- Machine authentication: short-lived Client Credentials tokens
- No reference to `auth.codestra.agency` is permitted
- External integrations and secrets remain server-side
- Production financial actions remain disabled until legal, security, vendor, and launch gates are approved

See [docs/BACKEND_IMPLEMENTATION_SPEC.md](docs/BACKEND_IMPLEMENTATION_SPEC.md) and [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

Detailed build sequence and implementation patterns: [Backend build blueprint](docs/BACKEND_BUILD_BLUEPRINT.md).

Mandatory launch gaps and evidence gates: [Production readiness requirements](docs/PRODUCTION_READINESS_REQUIREMENTS.md).
