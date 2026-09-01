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

## Architecture

There is no single `docker-compose.production.yml`. Deployment is split into
three digest-pinned Compose models, run together against one pair of Docker
networks (`moneybee_internal`, `moneybee_edge`), created once out-of-band:

- `compose.data.yml` — Postgres and Redis, each requiring an immutable image
  digest and a secrets file (no inline passwords).
- `compose.backend.yml` — the API, worker, and migrate services. Every image
  reference (`MONEYBEE_API_IMAGE`, `MONEYBEE_WORKER_IMAGE`,
  `MONEYBEE_MIGRATE_IMAGE`) must resolve to a `ghcr.io/.../moneybee-*@sha256:...`
  digest — none of these files ever contain a `build:` key (CI's
  `deployment-policy` job fails the pipeline if one appears), so there is
  nothing to build on the host. Images are built, scanned (Trivy), attested,
  and pushed by the `release-backend-images` GitHub Actions workflow
  (`workflow_dispatch` on `release/staging`), never locally.
- `compose.edge.yml` — Caddy, terminating TLS for the five public domains.

`ops/render-compose-env.py` renders the `MONEYBEE_*_IMAGE`/`MONEYBEE_*_PATH`
environment Compose needs from two reviewed, committed lock files:
`deploy/release.lock.json` (image digests, capability-freeze flags, release
evidence) and `deploy/runtime-paths.lock.json` (absolute host paths,
verified hostname). Both start `UNVERIFIED` and stay that way — and
`ops/validate-release-lock.py` / `ops/verify-runtime-env.py` fail closed on
anything else — until a human reviews and commits real evidence.
`ops/deploy-staging.sh` refuses to run at all today; it is an intentional
placeholder pending that separately reviewed executor.

## Prepare

```bash
cd /opt/moneybee/Moneybee-Backend/deploy
cp ../.env.production.example .env.production
chmod 600 .env.production
```

Replace every placeholder. Keep the canonical issuer `https://auth.codestra.co/realms/codestra`. The production API base URL is `https://api.moneybeeloan.com/api/v2`.

## Validate

Once `deploy/release.lock.json` and `deploy/runtime-paths.lock.json` carry
real, reviewed `VERIFIED` evidence (never edit them to `VERIFIED` without
that evidence actually existing):

```bash
python ops/validate-release-lock.py \
  --runtime-lock runtime-paths.lock.json --release-lock release.lock.json
python ops/verify-runtime-env.py \
  --env-file .env.production --release-lock release.lock.json
eval "$(python ops/render-compose-env.py \
  --runtime-lock runtime-paths.lock.json --release-lock release.lock.json)"
docker compose -f compose.data.yml -f compose.backend.yml -f compose.edge.yml config
```

## Migrate

```bash
docker compose -f compose.data.yml -f compose.backend.yml --profile migrate up migrate
```

Production uses Alembic. `AUTO_CREATE_SCHEMA` and `LOCAL_AUTH_BYPASS` must remain false — both are enforced by `ops/verify-runtime-env.py` above.

## Start and verify

```bash
docker compose -f compose.data.yml -f compose.backend.yml -f compose.edge.yml up -d
docker compose -f compose.data.yml -f compose.backend.yml -f compose.edge.yml ps
curl --fail https://api.moneybeeloan.com/health/ready
```

Verify all five public domains, Keycloak login, CORS, backups, log retention, outbox processing, and rollback before opening acquisition traffic.

## Not included automatically

This repository change does not install Docker, change DNS/firewall rules, connect to the host, provision Keycloak clients, inject real secrets, run migrations against production, or start containers. It also does not flip `deploy/release.lock.json` or `deploy/runtime-paths.lock.json` to `VERIFIED` — that requires a human to review and commit real evidence (see `docs/codex/PRODUCTION_100_MISSION.md` Phase 5).
