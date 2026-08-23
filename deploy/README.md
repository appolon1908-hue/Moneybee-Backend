# MoneyBee Hetzner deployment

Target layout:

```text
/opt/moneybee/
├── Moneybee-Backend/
└── Moneybee-frontend-/
```

The production Compose file is run from `Moneybee-Backend/deploy` and expects the frontend repository as the sibling directory shown above.

## Mandatory preflight

The proposed host `49.12.145.107` has also been used as a controlled scraper host. Inventory its running services, Docker networks, volumes, disk, memory, CPU, ports 80/443, backups, and rollback path before installing MoneyBee. Do not overwrite an existing reverse proxy or publish a conflicting port.

Create DNS A records for `@`, `www`, `app`, `lenders`, `admin`, and `api` to the approved server only after the service inventory and cutover plan are accepted. Do not create an AAAA record without configured IPv6.

At the Hetzner firewall expose TCP 80/443 publicly and restrict TCP 22 to approved administration addresses. Do not expose PostgreSQL 5432, Redis 6379, or FastAPI 8000.

## Prepare

```bash
cd /opt/moneybee/Moneybee-Backend/deploy
cp ../.env.production.example .env.production
chmod 600 .env.production
```

Replace every placeholder. Keep the canonical issuer `https://auth.codestra.co/realms/codestra`. The production API base URL is `https://api.moneybeeloan.com/api/v2`.

## Validate and migrate

```bash
docker compose --env-file .env.production -f docker-compose.production.yml config
docker compose --env-file .env.production -f docker-compose.production.yml build
docker compose --env-file .env.production -f docker-compose.production.yml run --rm api alembic upgrade head
```

Production uses Alembic. `AUTO_CREATE_SCHEMA` and `LOCAL_AUTH_BYPASS` must remain false.

## Start and verify

```bash
docker compose --env-file .env.production -f docker-compose.production.yml up -d
docker compose --env-file .env.production -f docker-compose.production.yml ps
curl --fail https://api.moneybeeloan.com/health/ready
```

Verify all five public domains, Keycloak login, CORS, backups, log retention, outbox processing, and rollback before opening acquisition traffic.

## Not included automatically

This repository change does not install Docker, change DNS/firewall rules, connect to the host, provision Keycloak clients, inject real secrets, run migrations against production, or start containers.
