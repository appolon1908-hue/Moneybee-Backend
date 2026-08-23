# MoneyBee Backend

Authoritative MoneyBeeLoans lending backend.

## Current status

`PARTIAL`

This repository is not yet approved for live lending or funding.

## Development

```bash
cp .env.example .env

docker compose -f compose.dev.yml up -d postgres redis

pip install -e ".[dev]"

alembic upgrade head

uvicorn app.main:app --reload
```

API: `http://localhost:8000`

Health: `GET /health/live`

Readiness: `GET /health/ready`

System readiness: `GET /api/v2/system/readiness`

## Capability freeze

The following remain disabled until launch certification:

- `credit.live_pull`
- `lenders.live_submission`
- `esign.live_send`
- `funding.live_confirmation`
- `payments`
- `payouts`

## Next PR

`auth/local-identity-tenancy`
