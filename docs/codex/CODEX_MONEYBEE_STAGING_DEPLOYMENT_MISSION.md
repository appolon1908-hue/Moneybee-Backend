# CODEX MISSION — MONEYBEE STAGING SERVER UPDATE

**Mission ID:** `MB-STAGING-SERVER-UPDATE-20260827`  
**Mission owner:** Ralph Appolon  
**Issued:** 2026-08-27  
**Execution mode:** staging-first, fail-closed, exact-SHA, evidence-driven  
**Production authorization:** **NOT GRANTED**

## Mission outcome

Integrate the reviewed MoneyBee authentication, portal-contract, finance-ledger, and secure deployment-scaffold work; produce protected staging release SHAs and immutable image digests; verify the candidate host without modifying it; and then update the **approved MoneyBee staging server only** through a protected deployment environment.

A GitHub Actions run that merely builds images or assembles a readiness packet is not a server deployment. Do not report `SERVER_UPDATED=YES` unless the remote host was changed, the exact deployed digests were verified on that host, health and identity checks passed, and rollback evidence was captured.

Do not deploy a feature branch directly. Do not deploy to production. Do not enable credit pulls, lender submission, e-sign, funding, payments, payouts, email, SMS, Odoo writes, n8n delivery, or any other external side effect.

## Verified source state

The following state was verified on 2026-08-27.

### Backend

Repository: `appolon1908-hue/Moneybee-Backend`

| Purpose | PR / branch | Exact head | Exact-head result |
|---|---|---|---|
| Secure split-image staging scaffold | PR #14, `ops/secure-staging-scaffold` | `c2f58171ef6e0c7816e9d362d8250ba6d4a61945` | backend and secure-scaffold CI passed |
| Keycloak account lifecycle and local tenancy | PR #15, `feature/keycloak-account-lifecycle` | `fb2866b033811bcb1c5e2522dc23bd350866164b` | backend and secure-scaffold CI passed |
| Finance ledger and normalized portal contracts | PR #16, `feature/financial-system-foundation` | `07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3` | backend and portal-stack CI passed |

The secure scaffold is a descendant of `release/portal-stack-consolidated`; it is not an unrelated root.

### Frontend

Repository: `appolon1908-hue/Moneybee-frontend-`

| Purpose | PR / branch | Exact head | Exact-head result |
|---|---|---|---|
| Secure frontend image scaffold | PR #16, `ops/secure-staging-scaffold` | `21869ac4cbe16da2e59226717d202e441adf37d0` | superseded by the OpenSSL fix below |
| Runtime OpenSSL repair | PR #17, `fix/frontend-runtime-openssl` | `7b67a2ed252de4c9e307933c3d2003502e2bc81c` | secure frontend CI passed |
| Finance portal and organization context | PR #19, `feature/financial-system-foundation` | `033e2190de4b9cf78f73c6d1a81f8668c5efef83` | frontend and portal-stack CI passed |
| Unified borrower/lender/admin/finance contracts and separate portal tokens | PR #20, `feature/keycloak-account-lifecycle` | `b7b0abb17a3325ba04941b60d548897a9bf7e93d` | secure frontend CI passed |

Frontend PR #18, `feat/enterprise-design-system`, targets `main` and is **not part of this staging-server mission**. Do not merge or deploy it as an accidental substitute for PR #20.

## Integration branches already created

Use these branches for the staging integration work. Do not force-push them and do not move them to unrelated commits.

```text
Backend:
integration/staging-moneybee-20260827
starts at fb2866b033811bcb1c5e2522dc23bd350866164b

Frontend:
integration/staging-moneybee-20260827
starts at b7b0abb17a3325ba04941b60d548897a9bf7e93d
```

## Required Git integration procedure

### Backend integration

1. Fetch all refs and confirm the integration branch still starts at the recorded SHA.
2. Merge exact finance head `07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3` into `integration/staging-moneybee-20260827` with a normal, reviewable merge commit.
3. Resolve only genuine integration conflicts. Do not remove the split-image scaffold, runtime-path locks, account bootstrap, portal-token checks, finance permissions, idempotency, audit, outbox, or migration safeguards.
4. Regenerate OpenAPI only through the repository script and commit the reviewed snapshot.
5. Run all backend gates at the exact resulting head.

Required backend gates:

```text
PYTHON_COMPILE=PASS
RUFF=PASS
PYTEST=PASS
POSTGRES_INTEGRATION=PASS
IDENTITY_TENANCY=PASS
PORTAL_CONTRACT_VALIDATION=PASS
OPENAPI_DRIFT=PASS
MIGRATION_EMPTY_TO_HEAD=PASS
MIGRATION_BASELINE_TO_HEAD=PASS
MIGRATION_DOWNGRADE_UPGRADE=PASS
BACKEND_API_IMAGE_BUILD=PASS
BACKEND_WORKER_IMAGE_BUILD=PASS
BACKEND_MIGRATE_IMAGE_BUILD=PASS
VULNERABILITY_GATE=PASS
```

### Frontend integration

1. Fetch all refs and confirm the integration branch still starts at the recorded SHA.
2. Merge exact finance head `033e2190de4b9cf78f73c6d1a81f8668c5efef83` into `integration/staging-moneybee-20260827` with a normal, reviewable merge commit.
3. Preserve the OpenSSL fix, separate borrower/lender/admin Keycloak client IDs, per-portal session storage, canonical API route builders, contract snapshot, and selected `X-Organization-ID` propagation.
4. Resolve duplicate API clients in favor of one typed client pattern. Do not reintroduce legacy generic `/portal/*` transport paths or singular lender decision routes.
5. Run all frontend gates at the exact resulting head.

Required frontend gates:

```text
PNPM_FROZEN_INSTALL=PASS
CONTRACTS_CHECK=PASS
TYPESCRIPT=PASS
VITEST=PASS
MARKETING_BUILD=PASS
BORROWER_BUILD=PASS
LENDER_BUILD=PASS
ADMIN_BUILD=PASS
MARKETING_IMAGE_BUILD=PASS
BORROWER_IMAGE_BUILD=PASS
LENDER_IMAGE_BUILD=PASS
ADMIN_IMAGE_BUILD=PASS
VULNERABILITY_GATE=PASS
```

### Protected staging release branches

After both integration heads are green:

1. Create `release/staging` in both repositories from the approved consolidated baseline.
2. Protect both branches before merging: pull requests required, exact-head checks required, independent approval required, conversations resolved, force pushes disabled, branch deletion disabled.
3. Open one backend integration PR and one frontend integration PR into `release/staging`.
4. Record the exact approved heads in both PR bodies.
5. Merge only through the protected controls.
6. Build release artifacts from the exact protected merged SHAs, never from the feature or integration branches.

If branch protection cannot be configured with the available authority, stop with `GO_NO_GO=NO_GO` and report the missing control. Do not create an unprotected release and call it protected.

## Canonical end-to-end request path to verify after deployment

For borrower, lender, administrator, and finance flows, prove this path with request IDs and database evidence:

```text
Vue portal
→ typed API client
→ portal-specific Keycloak Authorization Code + PKCE session
→ Authorization: Bearer <portal-specific token>
→ X-Organization-ID
→ X-Request-ID
→ X-Correlation-ID
→ Idempotency-Key for replay-sensitive mutations
→ If-Match for version-controlled writes
→ FastAPI /api/v2 route
→ JWT signature/issuer/audience/expiry validation
→ azp or client_id portal-token validation
→ local issuer + subject identity resolution
→ active organization, membership, permission and resource-scope enforcement
→ service/domain command
→ one PostgreSQL transaction
→ authoritative domain rows + idempotency evidence + audit event + outbox event
→ commit
→ typed OpenAPI response
→ frontend state
```

A borrower token must fail on lender and administrator routes with the reviewed portal-token mismatch response. Cross-organization query/body attempts must fail closed.

## Server gate: no mutation before read-only evidence

The current candidate is `49.12.145.107`, but it is not approved merely because it appears in an old workflow default.

Run the reviewed read-only preflight first, using the protected `staging-preflight` environment and strict known-host verification. The required script is:

```text
ops/runtime-path-preflight.sh
```

Capture and review:

```text
hostname and FQDN
public/private IPs
operating system and kernel
CPU, memory and disk capacity
Docker and Compose versions
running containers, networks and volumes
listening ports
firewall state
Caddy, Kong, Nginx and other edge ownership
existing databases and persistent volumes
backup destination
DNS ownership
SSH account and command restrictions
```

Expected MoneyBee candidate paths are:

```text
/opt/moneybee/releases
/opt/moneybee/current
/etc/moneybee/backend.env
/etc/moneybee/secrets/postgres_password
/etc/moneybee/secrets/redis.acl
/var/lib/moneybee/postgres
/var/lib/moneybee/redis
/var/lib/moneybee/caddy/data
/var/lib/moneybee/caddy/config
/var/backups/moneybee
```

Do not create, chmod, chown, move, delete, restart, stop, or overwrite anything during preflight.

Abort if the candidate host is owned by another workload, the proposed paths collide with an existing system, resources are insufficient, edge ownership is unclear, or backup storage is unresolved.

Convert approved evidence into a reviewed `deploy/runtime-paths.lock.json` containing the raw-evidence SHA-256. Never fabricate a runtime lock from proposed values.

## Immutable release artifacts

Publish and deploy separate images by digest:

```text
ghcr.io/appolon1908-hue/moneybee-backend
ghcr.io/appolon1908-hue/moneybee-worker
ghcr.io/appolon1908-hue/moneybee-migrate
ghcr.io/appolon1908-hue/moneybee-marketing
ghcr.io/appolon1908-hue/moneybee-borrower
ghcr.io/appolon1908-hue/moneybee-lender
ghcr.io/appolon1908-hue/moneybee-admin
```

For every image record:

```text
protected source SHA
immutable image digest
SBOM digest
vulnerability result
provenance/attestation
signature verification
build timestamp
release identity label
```

The target host must never run `docker compose build`. It may only pull the digests recorded in the reviewed `deploy/release.lock.json`.

## Readiness packet is not deployment

The existing workflow named `staging-deployment-readiness-packet` only validates locks and assembles a review artifact. Its own output states:

```text
REMOTE_DEPLOYMENT=NOT_PERFORMED
LIVE_SERVER_CHANGED=NO
```

Do not report a server update after running that workflow.

## Actual staging deployment executor

If no reviewed remote executor exists, add one in a focused, independently reviewed operations PR. It must:

1. Run only from `refs/heads/release/staging`.
2. Use the protected `staging-deploy` GitHub environment.
3. Require the exact confirmation string `APPLY-MONEYBEE-STAGING-49.12.145.107`.
4. Verify the backend SHA, frontend SHA, runtime-lock hash, release-lock hash, configuration checksum, and every image digest before SSH.
5. Use strict known-host validation and a dedicated least-privilege deployment identity. Prefer a forced-command or allowlisted deployment wrapper; do not expose unrestricted root SSH merely for convenience.
6. Refuse mutable image tags and refuse Compose files containing `build:`.
7. Create a timestamped release directory beneath `/opt/moneybee/releases` and never edit the previous release in place.
8. Capture the previous `/opt/moneybee/current` target and deployed digest tuple before applying changes.
9. Take and verify a PostgreSQL backup before migrations.
10. Run the one-shot migration image and require a single Alembic head.
11. Start data services privately, then API, workers, and the four frontend services, then the reviewed edge service.
12. Keep all external and live-finance capabilities disabled.
13. Verify health, readiness, version identity, container digests, restart behavior, logs, and database connectivity.
14. Switch `/opt/moneybee/current` atomically only after all checks pass.
15. Roll back automatically to the previous reviewed release tuple when a post-deploy check fails.
16. Upload non-secret deployment and rollback evidence as a GitHub artifact.

Do not put SSH private keys, registry tokens, database passwords, Redis ACLs, Keycloak secrets, SMTP credentials, provider credentials, or DKIM private keys in Git, issue comments, workflow artifacts, Docker labels, or command output.

## Required staging capability freeze

The deployed environment must fail closed with all external effects disabled:

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
PRODUCTION_DIALING=DISABLED
```

Use the repository's canonical variable names where they differ, but the effective capability state must remain false. Disabled workers must not consume pending external-delivery events.

## Database gate

Before rollout, record:

```text
BACKUP=PASS
BACKUP_SHA256=<digest>
RESTORE_TEST=PASS
RPO=<recorded value>
RTO=<recorded value>
ALEMBIC_HEAD=<single revision>
EMPTY_TO_HEAD=PASS
BASELINE_TO_HEAD=PASS
DOWNGRADE_UPGRADE=PASS
```

Do not use `Base.metadata.create_all()` in staging. Do not use SQLite as migration or transaction evidence.

## Staging smoke and security validation

Verify the approved staging hostnames or reviewed temporary host-header equivalents:

```text
staging.moneybeeloan.com
app-staging.moneybeeloan.com
lenders-staging.moneybeeloan.com
admin-staging.moneybeeloan.com
api-staging.moneybeeloan.com
```

Required checks:

```text
DNS/TLS or approved temporary routing=PASS
CORS exact origins=PASS
security headers=PASS
PostgreSQL private-only=PASS
Redis private-only=PASS
/api/v2/health=PASS
/api/v2/ready=PASS
/api/v2/version=PASS
release SHA and digest identity=PASS
borrower PKCE login and callback=PASS
lender PKCE login and callback=PASS
admin PKCE login and callback=PASS
portal-token separation=PASS
organization selection and tenant isolation=PASS
borrower workspace=PASS
lender workspace=PASS
admin workspace=PASS
finance accounts/periods/journals/trial balance=PASS
idempotent replay=PASS
idempotency collision rejection=PASS
optimistic-concurrency rejection=PASS
migration restart behavior=PASS
container restart behavior=PASS
rollback exercise=PASS
external deliveries observed=0
live financial actions observed=0
```

The finance screen records accounting state only. It must not initiate ACH, wire, card, lender funding, credit, or provider calls.

## Stop conditions

Stop immediately and report `GO_NO_GO=NO_GO` when any of these is true:

- an exact source SHA moved or cannot be verified;
- required CI is not green at the integration or protected merged head;
- review or branch protection is missing;
- the runtime host or path ownership is unresolved;
- SSH known-host evidence or protected environment secrets are missing;
- a release image is mutable, unsigned, unscanned, or not tied to the protected SHA;
- backup or restore verification fails;
- migration creates multiple heads or rollback is unproven;
- any external/live capability resolves true;
- a health, tenant-isolation, portal-token, finance, restart, or rollback test fails;
- the deployment executor cannot prove the exact remote digest tuple.

Do not weaken a gate, use a wildcard redirect, bypass Keycloak, manually edit production-like data, or run unreviewed commands to force a pass.

## Required final Codex report

Return one evidence record containing:

```text
MISSION_ID=MB-STAGING-SERVER-UPDATE-20260827
BACKEND_INTEGRATION_SHA=<sha>
FRONTEND_INTEGRATION_SHA=<sha>
BACKEND_RELEASE_SHA=<protected merged sha>
FRONTEND_RELEASE_SHA=<protected merged sha>
BACKEND_IMAGE_DIGESTS=<digests>
FRONTEND_IMAGE_DIGESTS=<digests>
RUNTIME_PREFLIGHT_RUN=<run or evidence reference>
RUNTIME_EVIDENCE_SHA256=<digest>
RELEASE_LOCK_SHA256=<digest>
CONFIGURATION_CHECKSUM=<digest>
BACKUP_REFERENCE=<reference>
BACKUP_SHA256=<digest>
MIGRATION_HEAD=<revision>
DEPLOYMENT_RUN=<run or change reference>
TARGET_HOST=<verified host>
DEPLOYED_RELEASE_ROOT=<path>
REMOTE_BACKEND_DIGEST=<digest>
REMOTE_FRONTEND_DIGESTS=<digests>
HEALTH=PASS|FAIL
READY=PASS|FAIL
VERSION_IDENTITY=PASS|FAIL
TENANT_ISOLATION=PASS|FAIL
PORTAL_TOKEN_SEPARATION=PASS|FAIL
FINANCE_SMOKE=PASS|FAIL
ROLLBACK=PASS|FAIL
EXTERNAL_DELIVERIES=0
LIVE_FINANCIAL_ACTIONS=0
SERVER_UPDATED=YES|NO
PRODUCTION_CHANGED=NO
GO_NO_GO=GO|NO_GO
BLOCKERS=<none or exact blockers>
```

`SERVER_UPDATED=YES` is permitted only after remote digest and runtime evidence proves the staging host changed successfully. Otherwise report `SERVER_UPDATED=NO` without ambiguity.
