# MoneyBee Codex Repository and File Allowlist

This file is a controlling boundary for mission `MB-CODE-AND-RELEASE-READINESS-20260827`.

```text
REPOSITORY_SCOPE_ENFORCED=YES
ALLOWED_REPOSITORY_COUNT=2
OTHER_REPOSITORIES_ALLOWED=NO
CROSS_REPOSITORY_SOURCE_COPYING_ALLOWED=NO
SERVER_ACCESS_ALLOWED=NO
```

## The only allowed Git repositories

Codex may read and update application code only in these two exact repositories:

```text
BACKEND_REPOSITORY=appolon1908-hue/Moneybee-Backend
BACKEND_URL=https://github.com/appolon1908-hue/Moneybee-Backend

FRONTEND_REPOSITORY=appolon1908-hue/Moneybee-frontend-
FRONTEND_URL=https://github.com/appolon1908-hue/Moneybee-frontend-
```

Before changing code, verify each clone:

```bash
git remote get-url origin
git rev-parse --show-toplevel
git status --short --branch
```

The origin must resolve to the exact allowlisted repository. Stop when the repository is a fork, duplicate, renamed substitute, unrelated checkout, or a directory without the expected Git origin.

## Writable integration branches

Codex may write application-integration commits only to:

```text
Backend:
integration/staging-moneybee-20260827
expected starting SHA: fb2866b033811bcb1c5e2522dc23bd350866164b

Frontend:
integration/staging-moneybee-20260827
expected starting SHA: b7b0abb17a3325ba04941b60d548897a9bf7e93d
```

Do not force-push either branch.

The mission branch below is the read-only instruction source for Codex. Codex must not use it as an application integration branch:

```text
appolon1908-hue/Moneybee-Backend
ops/codex-staging-deployment-mission
```

## Read-only source refs

Only these reviewed source heads may be integrated into the writable branches:

```text
Backend account/identity source:
feature/keycloak-account-lifecycle
fb2866b033811bcb1c5e2522dc23bd350866164b

Backend finance/API source:
feature/financial-system-foundation
07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3

Frontend account/portal-contract source:
feature/keycloak-account-lifecycle
b7b0abb17a3325ba04941b60d548897a9bf7e93d

Frontend finance source:
feature/financial-system-foundation
033e2190de4b9cf78f73c6d1a81f8668c5efef83
```

Do not substitute `main`, an older portal branch, an automation snapshot, or frontend PR #18 for these refs.

## Backend file ownership

Backend code and backend-owned release files belong only in `Moneybee-Backend`.

Codex may update these backend paths when required by the focused integration:

```text
app/**
migrations/**
tests/**
scripts/**
docs/**
deploy/**
docker/**
ops/**
.github/workflows/**
openapi.json
pyproject.toml
alembic.ini
Dockerfile
docker-compose.yml
.env.example
.env.production.example
README.md
```

Backend responsibilities include:

```text
FastAPI routes and schemas
service and domain logic
Keycloak token and local identity enforcement
tenant, role, permission and resource checks
PostgreSQL models and Alembic migrations
idempotency, optimistic concurrency, audit and outbox/inbox logic
finance ledger and database controls
provider and middleware contracts
backend API, worker and migration containers
backend/data/edge Compose and release-readiness files
backend CI and OpenAPI validation
```

Do not place Vue pages, frontend API clients, browser auth code, frontend Nginx assets, or frontend application source in the backend repository.

## Frontend file ownership

Frontend code and frontend-owned image files belong only in `Moneybee-frontend-`.

Codex may update these frontend paths when required by the focused integration:

```text
apps/marketing/**
apps/borrower/**
apps/lender/**
apps/admin/**
packages/api-client/**
packages/auth/**
packages/ui/**
packages/design-system/**
scripts/**
docs/**
deploy/**
.github/workflows/**
Dockerfile
nginx.conf
nginx-main.conf
package.json
pnpm-lock.yaml
pnpm-workspace.yaml
tsconfig*.json
.env.example
.env.production.example
README.md
```

Frontend responsibilities include:

```text
marketing, borrower, lender and admin Vue applications
portal routes and views
typed API clients and backend-contract snapshots
Authorization Code + PKCE browser authentication
separate borrower, lender and admin Keycloak client/session boundaries
form validation and accessible error handling
frontend unit, component and browser tests
marketing, borrower, lender and admin containers
frontend Compose and image-release files
frontend CI, frozen lockfile and vulnerability gates
```

Do not place FastAPI, SQLAlchemy, Alembic, PostgreSQL models, backend workers, Odoo adapters, or backend secrets in the frontend repository.

## Explicit repository exclusions

Codex must not read from or write to another repository as part of this mission, including but not limited to:

```text
appolon1908-hue/OdooMiddleware
appolon1908-hue/N8N
appolon1908-hue/codestra
appolon1908-hue/klyrow-Website-
appolon1908-hue/Telnexa-web
appolon1908-hue/Breero.com
appolon1908-hue/scrapper
any server-side repository or untracked checkout
any fork or similarly named MoneyBee repository
```

Integration with Codestra, Odoo, Klyrow/Postal, Keycloak, n8n, lenders, banks, credit providers, or other systems is represented only through reviewed contracts and disabled configuration examples inside the two allowlisted MoneyBee repositories. This mission does not authorize changes to those external repositories or systems.

## Git and deployment exclusions

Codex must not:

```text
modify main
modify or create release/staging
modify release/production
merge pull requests
force-push
deploy a branch
contact 49.12.145.107
dispatch host-contacting workflows
copy frontend source into backend
copy backend source into frontend
use a sibling-repository Docker build context
commit credentials, tokens, SMTP passwords or DKIM private keys
```

## Required stop response

If work requires a third repository, an excluded path, a server, an external account, or a branch outside this allowlist, stop and report:

```text
REPOSITORY_SCOPE_VIOLATION=YES
REQUESTED_REPOSITORY=<repository or system>
REQUESTED_PATH=<path or NONE>
CHANGE_PERFORMED=NO
SERVER_UPDATED=NO
STAGING_DEPLOYED=NO
PRODUCTION_CHANGED=NO
GO_NO_GO=NO_GO
```
