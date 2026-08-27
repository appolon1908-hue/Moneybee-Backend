# MoneyBee Codex Start Here

## Current mission

Read these files in order:

1. `docs/codex/MONEYBEE_REPOSITORY_ALLOWLIST.md`
2. `docs/codex/CODEX_MONEYBEE_STAGING_DEPLOYMENT_MISSION.md`

Mission ID:

```text
MB-CODE-AND-RELEASE-READINESS-20260827
```

## Mandatory repository boundary

Codex may use only these two exact repositories:

```text
BACKEND_REPOSITORY=appolon1908-hue/Moneybee-Backend
FRONTEND_REPOSITORY=appolon1908-hue/Moneybee-frontend-
ALLOWED_REPOSITORY_COUNT=2
OTHER_REPOSITORIES_ALLOWED=NO
```

The detailed branch and file-path allowlist in `docs/codex/MONEYBEE_REPOSITORY_ALLOWLIST.md` is controlling. Stop before reading from, writing to, cloning, patching, or creating a pull request in any other repository.

Application integration commits may be written only to:

```text
Backend: integration/staging-moneybee-20260827
Frontend: integration/staging-moneybee-20260827
```

Do not mix source ownership: frontend remains in `Moneybee-frontend-`; backend, database and workers remain in `Moneybee-Backend`.

## Authorization boundary

This mission authorizes **repository code work, integration-branch updates, automated validation, draft pull requests, release-plan preparation, and non-secret evidence generation only**.

It does **not** authorize a staging-server update, production change, SSH execution, workflow dispatch that contacts a host, DNS/firewall/proxy change, server-side migration, container rollout, secret injection, Keycloak/SMTP configuration, middleware/Odoo activation, or any external/live financial capability.

```text
STAGING_SERVER_UPDATE_AUTHORIZED=NO
PRODUCTION_CHANGE_AUTHORIZED=NO
SSH_EXECUTION_AUTHORIZED=NO
READ_ONLY_PREFLIGHT_AUTHORIZED=NO
DEPLOYMENT_WORKFLOW_DISPATCH_AUTHORIZED=NO
AUTO_MERGE_AUTHORIZED=NO
```

PR #11 and issue #18 are task-definition and review artifacts only. They are not execution authority for a server or production environment.

## Integration branches

```text
Backend repository:
appolon1908-hue/Moneybee-Backend
integration/staging-moneybee-20260827
starting SHA: fb2866b033811bcb1c5e2522dc23bd350866164b
finance head to integrate: 07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3

Frontend repository:
appolon1908-hue/Moneybee-frontend-
integration/staging-moneybee-20260827
starting SHA: b7b0abb17a3325ba04941b60d548897a9bf7e93d
finance head to integrate: 033e2190de4b9cf78f73c6d1a81f8668c5efef83
```

Frontend PR #18 is a separate design-system PR and is not part of this account/portal/finance integration mission.

## Permitted execution order

1. Verify both exact repository origins against the allowlist.
2. Verify every recorded source SHA and exact-head workflow result.
3. Integrate the exact finance heads into the dedicated integration branches with reviewable commits.
4. Resolve only genuine integration conflicts; preserve split frontend/backend Docker ownership, portal-specific tokens, tenant isolation, migrations, idempotency, audit and outbox controls.
5. Run complete backend and frontend contract, PostgreSQL, migration, type, test, build and vulnerability gates.
6. Repair failures on the integration branches and rerun exact-head checks.
7. Open or update focused **draft** pull requests for review in the same two repositories only.
8. Prepare release-lock templates, runtime-path questions, rollback instructions and a review-only readiness packet containing no secrets.
9. Stop and report the exact remaining blockers.

## Explicitly prohibited

Codex must not:

- use any repository other than `appolon1908-hue/Moneybee-Backend` and `appolon1908-hue/Moneybee-frontend-`;
- copy frontend source into the backend repository;
- copy backend, database or worker source into the frontend repository;
- use a sibling-repository Docker build context;
- modify `main`, `release/staging`, or `release/production`;
- merge a protected or release pull request;
- create or move a deployment tag;
- publish or deploy an image as an approved release;
- dispatch `runtime-path-preflight-read-only`, `staging-deployment-readiness-packet`, or any SSH/deployment workflow;
- contact or modify `49.12.145.107`;
- create, chmod, chown, move, delete or overwrite server paths;
- run migrations against a staging or production database;
- pull, start, stop or restart remote containers;
- change Caddy, Nginx, Kong, DNS, firewall, Keycloak, Klyrow/Postal, Codestra, Odoo or n8n;
- enable external delivery, email, SMS, credit, lender submission, e-sign, funding, payment or payout capabilities;
- place credentials, access tokens, refresh tokens, SMTP passwords or DKIM private keys in Git, comments, artifacts or logs;
- report `SERVER_UPDATED=YES`, `STAGING_DEPLOYED=YES` or `PRODUCTION_CHANGED=YES`.

## Capability freeze

```text
ENABLE_EXTERNAL_DELIVERY=false
MIDDLEWARE_PROVIDER=disabled
LIVE_WRITES=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false
CREDIT_LIVE_PULL=false
LENDERS_LIVE_SUBMISSION=false
ESIGN_LIVE_SEND=false
FUNDING_LIVE_CONFIRMATION=false
PAYMENTS_ENABLED=false
PAYOUTS_ENABLED=false
COMMUNICATIONS_LIVE_EMAIL=false
COMMUNICATIONS_LIVE_SMS=false
```

## Required final Codex record

```text
MISSION_ID=MB-CODE-AND-RELEASE-READINESS-20260827
REPOSITORY_SCOPE_ENFORCED=YES
BACKEND_REPOSITORY=appolon1908-hue/Moneybee-Backend
FRONTEND_REPOSITORY=appolon1908-hue/Moneybee-frontend-
OTHER_REPOSITORIES_USED=NO
BACKEND_INTEGRATION_SHA=<sha or BLOCKED>
FRONTEND_INTEGRATION_SHA=<sha or BLOCKED>
BACKEND_EXACT_HEAD_CI=<PASS|FAIL|PENDING>
FRONTEND_EXACT_HEAD_CI=<PASS|FAIL|PENDING>
CONTRACT_ALIGNMENT=<PASS|FAIL>
POSTGRES_AND_MIGRATIONS=<PASS|FAIL>
FRONTEND_IMAGE_SECURITY=<PASS|FAIL>
DRAFT_PRS_READY=<YES|NO>
RELEASE_PLAN_READY=<YES|NO>
READ_ONLY_PREFLIGHT_RUN=NOT_AUTHORIZED
SERVER_UPDATED=NO
STAGING_DEPLOYED=NO
PRODUCTION_CHANGED=NO
GO_NO_GO=NO_GO
BLOCKERS=<exact blockers>
```

A separate explicit authorization must be issued before any read-only host contact or staging-server mutation.
