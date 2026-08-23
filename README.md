# MoneyBee Backend

Authoritative Python/FastAPI backend for **MoneyBeeLoans** — “Business funding that keeps you moving.”

## Included baseline
- Versioned FastAPI API and health probes
- PostgreSQL/SQLAlchemy models and Alembic migration
- Keycloak JWT validation against `https://auth.codestra.co/realms/codestra`
- Role enforcement, correlation IDs, audit events, idempotent intake, signed webhook ingestion
- Docker Compose with PostgreSQL 17 and Redis
- CI lint/compile/tests and production readiness gates

## Local start
```bash
cp .env.example .env
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up --build api
```

Public API contract: `docs/API_CONTRACT.md`. Production gate: `docs/PRODUCTION_READINESS.md`.

Live lender submission and funding actions are **disabled by default** and must not be enabled until legal, security, vendor, and launch gates are approved.
