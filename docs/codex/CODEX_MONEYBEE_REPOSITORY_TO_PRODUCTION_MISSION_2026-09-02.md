# CODEX MONEYBEE REPOSITORY-TO-PRODUCTION MISSION

```text
MISSION_ID=MONEYBEE_REPOSITORY_TO_PRODUCTION_2026_09_02
MISSION_OWNER=Ralph Appolon
EXECUTOR=Codex
PRIMARY_BACKEND_REPOSITORY=appolon1908-hue/Moneybee-Backend
PRIMARY_FRONTEND_REPOSITORY=appolon1908-hue/Moneybee-frontend-
TARGET_PRODUCTION_HOST=49.12.145.107
REPOSITORY_FIRST=MANDATORY
SSH_CONFIGURATION_CHANGES=FORBIDDEN
INITIAL_LIVE_PROVIDER_EFFECTS=DISABLED
```

## 1. Mission

Finish, verify, merge, and release the authoritative MoneyBee backend and frontend repositories, then pull and install only the resulting immutable release on the production host. Make the MoneyBee website, portals, identity boundary, database-backed core API, monitoring, and rollback path live while every external provider and consequential financial effect remains disabled until its own separate activation gate passes.

Do not treat this document as permission to skip repository work, branch protection, test failures, review findings, artifact provenance, backup/restore validation, or runtime safety gates.

Continue repository remediation until every required exact-head gate is green. Server work may begin only after the repository certification section below is satisfied. Stop server mutation immediately on any safety, identity, data, source-lock, backup, or rollback failure.

## 2. Current authoritative state at mission publication

```text
BACKEND_MAIN_SHA=aa6a8413b79885c499482b53e0c3ffaf8637c9d4
BACKEND_RELEASE_PR=42
BACKEND_RELEASE_BRANCH=release/moneybee-repository-complete-20260902
BACKEND_RELEASE_HEAD=b8682c4542738caae9f58c00f628a7f74dccfb10
BACKEND_RELEASE_STATE=OPEN_DRAFT
BACKEND_CURRENT_EXACT_HEAD_CI=FAIL

FRONTEND_MAIN_SHA=b40d519ccc4318f0525171b1d71f64176daabbd2
FRONTEND_RELEASE_PR=27
FRONTEND_RELEASE_BRANCH=release/moneybee-frontend-repository-complete-20260902
FRONTEND_RELEASE_HEAD=7058cd7c49b59931bc8c462e721511fd0b77f012
FRONTEND_RELEASE_STATE=OPEN_DRAFT
FRONTEND_LAST_CERTIFIED_BACKEND_CONTRACT=bb5e00016be80c036500fb8cb382b3c47fd88c9b

CONNECTOR_SDK_REPOSITORY=appolon1908-hue/SDK-repository
CONNECTOR_SDK_SHA=fd9a5c3fd49534a7f7492a452f53815c386687b9
ALEMBIC_HEAD=20260901_0026
SERVER_HANDOFF_ISSUE=appolon1908-hue/Moneybee-Backend#44
```

The frontend is not allowed to remain certified against `bb5e000...` after the backend release head changes. It must be revalidated against the final exact backend release or merge SHA.

## 3. Current backend blockers that must be repaired first

The exact backend release head `b8682c4542738caae9f58c00f628a7f74dccfb10` currently fails four production-critical tests:

1. `test_legacy_offer_acknowledgment_uses_audit_and_durable_idempotency`
   - The legacy offer-disclosure acknowledgment returns HTTP 200 but writes no matching audit event.
   - Required result: one durable audit event and one durable idempotency record for the first successful command; deterministic replay returns the original result without a second audit event.

2. `test_concurrent_tax_filing_same_key_replays_instead_of_raising_integrity_error`
   - Two concurrent requests using the same idempotency identity can race into `uq_idempotency_actor_route_key` and surface a PostgreSQL `UniqueViolationError`/SQLAlchemy `IntegrityError`.
   - Required result: serialize or conflict-safe the identity before side effects; same key plus same request must replay one durable result; same key plus a changed request hash must return the canonical idempotency conflict; no raw database integrity error may escape.

3. `test_void_response_loss_is_reconciled_before_local_transition`
   - A simulated DocuSign void accepted upstream with the response lost returns HTTP 503 instead of performing read-back and safely completing the local transition when provider status confirms `voided`.
   - Required result: one provider mutation attempt, durable ambiguous-outcome evidence, provider read-back, and local transition only when the read-back proves the upstream state.

4. `test_unknown_void_blocks_repeat_until_readback_confirms`
   - A truly unresolved void outcome returns generic `REQUEST_FAILED` instead of `CONTRACT_VOID_RECONCILIATION_REQUIRED`.
   - Required result: record the ambiguous outcome durably, do not automatically repeat the consequential provider mutation, expose the canonical reconciliation-required error and operation state, and permit only controlled reconciliation/read-back.

Do not delete or weaken these tests. Repair the application behavior and add any missing focused PostgreSQL, audit, replay, rollback, and no-repeat tests.

## 4. Absolute rules

- Work in GitHub repositories first. No server-side source patch is allowed.
- Do not change SSH keys, `authorized_keys`, `sshd_config`, SSH users, sudo policy, or SSH firewall rules.
- Do not force-push protected or shared branches.
- Do not bypass required checks or dismiss valid reviews merely to merge.
- Do not deploy from a branch name, mutable tag, `latest`, local working tree, or server checkout.
- Do not put secrets in Git, issue comments, PR bodies, Actions logs, command-line arguments, shell history, Docker metadata, or evidence files.
- Do not grant the API or worker PostgreSQL superuser, owner, DDL, role-management, database-creation, replication, or bypass-RLS privileges.
- Do not run Alembic or schema creation from API/worker startup.
- Do not expose Docker socket access to application containers.
- Do not call external providers from migration, startup, readiness, or repository tests.
- Do not automatically retry a consequential provider mutation after an ambiguous response.
- Do not enable credit pulls, lender submissions, e-sign sends, funding, payments, payouts, tax filing, email, SMS, Odoo writes, n8n delivery, object storage, malware scanning, or Codestra SDK commands in the initial production release.
- Do not claim production certification from repository CI alone; runtime backup, restore, identity, routing, and rollback evidence are required.

## 5. Phase A — complete and normalize repository authority

### A1. Backend repository

1. Fetch the authoritative backend repository and verify the remote origin exactly.
2. Check out PR #42 head without modifying `main` directly.
3. Rebase or merge current protected `main` only when required and without losing reviewed behavior.
4. Inventory every open MoneyBee backend PR and identify which changes are:
   - already included in PR #42;
   - still missing and required;
   - obsolete or superseded;
   - unrelated and intentionally excluded.
5. Do not close an older PR until its required content is demonstrably included or explicitly rejected with evidence.
6. Repair all current exact-head failures, including the four listed above.
7. Preserve:
   - canonical `/api/v2` OpenAPI;
   - hidden `/api/v1` compatibility aliases using the same business logic;
   - borrower/lender/admin client and tenant separation;
   - local `(issuer, subject)` identity binding;
   - server-authoritative authorization;
   - Decimal-based money values;
   - immutable audit and idempotency evidence;
   - one-attempt consequential provider behavior;
   - durable inbox/outbox, retry, reconciliation, and operational-exception state;
   - runtime/migrator database-role separation;
   - all external capability defaults disabled.
8. Remove temporary branch-writer, self-modifying, or review-fix workflows that are not part of the normal protected release process.
9. Update generated OpenAPI and endpoint catalog only through their canonical generators.
10. Update PR #42 body with the final exact head, all exact workflow run links, migration head, OpenAPI/catalog digests, image/SBOM evidence, and known limitations.

### A2. Backend required gates

All must pass on the same unchanged exact backend head:

```text
GIT_DIFF_CHECK=PASS
RUFF=PASS
COMPILEALL=PASS
PRIVATE_KEY_SCAN=PASS
DEPENDENCY_CHECK=PASS
ALEMBIC_SINGLE_HEAD=PASS
POSTGRES_EMPTY_TO_HEAD=PASS
POSTGRES_HISTORICAL_TO_HEAD=PASS
MIGRATION_DOWNGRADE_REUPGRADE=PASS
MIGRATION_UNSAFE_DOWNGRADE_GUARDS=PASS
RUNTIME_DATABASE_DDL_DENIAL=PASS
IDENTITY_TENANCY_TESTS=PASS
IDEMPOTENCY_REPLAY_AND_RACE_TESTS=PASS
AUDIT_EVIDENCE_TESTS=PASS
PROVIDER_AMBIGUOUS_OUTCOME_TESTS=PASS
FULL_PYTEST=PASS
OPENAPI_DRIFT=PASS
ENDPOINT_CATALOG_DRIFT=PASS
API_SMOKE=PASS
API_IMAGE_BUILD=PASS
WORKER_IMAGE_BUILD=PASS
MIGRATOR_IMAGE_BUILD=PASS
HIGH_CRITICAL_VULNERABILITY_POLICY=PASS
SBOM_GENERATION=PASS
SECURE_SCAFFOLD_CI=PASS
BACKEND_CI=PASS
CODE_REVIEW=PASS
```

A skipped required gate is not a pass unless the gate is explicitly not applicable and documented.

### A3. Frontend repository

1. Fetch the authoritative frontend repository and verify the remote origin exactly.
2. Check out PR #27 head without modifying `main` directly.
3. Inventory all open frontend PRs and prove which required changes are included in PR #27.
4. Preserve the four applications:
   - marketing;
   - borrower portal;
   - lender portal;
   - administrator portal.
5. Preserve browser/server trust boundaries:
   - Keycloak Authorization Code plus PKCE for humans;
   - no browser client secret;
   - no provider, database, OpenBao, Odoo, lender, DocuSign, email, SMS, storage, or Codestra service credential in browser source or images;
   - backend permissions and tenant scope remain authoritative;
   - no direct browser calls to Middleware, Odoo, n8n, PostgreSQL, Redis, or providers.
6. Replace the old backend contract lock with the final exact backend release/merge SHA.
7. Check out that exact backend commit in frontend CI, assert `git rev-parse HEAD`, export runtime OpenAPI, and retain the contract evidence artifact.
8. Update every generated/typed client and UI binding needed for the final backend contract.
9. Test authentication, organization context, URI encoding, idempotency, offline/ambiguous errors, write-only TIN behavior, decimal display, legal/compliance wording, responsive layouts, accessibility, loading/empty/error states, and protected deep links.
10. Update PR #27 body with the final exact head, final backend contract SHA, workflow run, contract artifact digest, all image scan results, and known limitations.

### A4. Frontend required gates

All must pass on the same unchanged exact frontend head against the final backend contract:

```text
FROZEN_DEPENDENCY_INSTALL=PASS
BACKEND_SHA_ASSERTION=PASS
RUNTIME_OPENAPI_EXPORT=PASS
FRONTEND_BACKEND_ROUTE_DRIFT=PASS
TYPESCRIPT=PASS
UNIT_TESTS=PASS
MARKETING_BUILD=PASS
BORROWER_BUILD=PASS
LENDER_BUILD=PASS
ADMIN_BUILD=PASS
FRONTEND_SCAFFOLD_VALIDATION=PASS
MARKETING_IMAGE_BUILD_SCAN=PASS
BORROWER_IMAGE_BUILD_SCAN=PASS
LENDER_IMAGE_BUILD_SCAN=PASS
ADMIN_IMAGE_BUILD_SCAN=PASS
CONTRACT_EVIDENCE_ARTIFACT=PASS
SECURE_FRONTEND_CI=PASS
CODE_REVIEW=PASS
```

## 6. Phase B — protected merge and repository cleanup

1. Mark PR #42 ready only after all backend gates pass on its exact head.
2. Resolve every valid review thread with source and test evidence.
3. Merge PR #42 through the configured protected process. Do not bypass branch protection.
4. Record the exact backend merge SHA from `main`.
5. Update frontend PR #27 to lock against that backend merge SHA and rerun every frontend gate.
6. Mark PR #27 ready only after all frontend gates pass on its exact head.
7. Resolve every valid frontend review thread.
8. Merge PR #27 through the configured protected process.
9. Record the exact frontend merge SHA from `main`.
10. Verify both clean protected `main` branches reproduce their required gates.
11. Close superseded PRs only after adding a traceability comment naming the authoritative merge SHA.
12. Update repository READMEs, architecture, API, deployment, rollback, operations, security, and evidence documentation so no obsolete branch or source authority is presented as deployable.

Repository phase may be certified only when:

```text
BACKEND_MAIN_CONTAINS_CERTIFIED_RELEASE=YES
FRONTEND_MAIN_CONTAINS_CERTIFIED_RELEASE=YES
BACKEND_MAIN_EXACT_GATES=PASS
FRONTEND_MAIN_EXACT_GATES=PASS
FRONTEND_LOCKED_TO_BACKEND_MERGE_SHA=YES
OPEN_REVIEW_FINDINGS=0
UNEXPLAINED_REQUIRED_PR_CONTENT=0
SERVER_SIDE_PATCHES=0
REPOSITORY_PHASE_CERTIFIED=YES
```

## 7. Phase C — immutable release artifacts and source lock

From the exact merged `main` SHAs:

1. Publish separate immutable images for:
   - backend API;
   - backend worker;
   - backend migrator;
   - marketing frontend;
   - borrower frontend;
   - lender frontend;
   - administrator frontend.
2. Every image must have a registry digest and these OCI labels:
   - `org.opencontainers.image.source`;
   - `org.opencontainers.image.revision`;
   - version/release identity.
3. Generate and retain an SBOM for every image.
4. Generate and retain provenance/attestation for every image.
5. Enforce the fixable HIGH/CRITICAL vulnerability policy.
6. Sign or attest images using the approved release mechanism.
7. Ensure production Compose files contain no `build:` entries and reference only immutable image digests.
8. Produce a reviewed release lock containing:

```text
backend_merge_sha
frontend_merge_sha
connector_sdk_sha
alembic_head
api_image_digest
worker_image_digest
migrator_image_digest
marketing_image_digest
borrower_image_digest
lender_image_digest
admin_image_digest
openapi_digest
endpoint_catalog_digest
sbom_digests
provenance_digests
compose_checksums
configuration_template_checksum
rollback_image_digests
```

9. Commit the release lock and release evidence to a reviewed repository PR. Do not place secret values in it.
10. Update issue #44 with the exact merge SHAs and immutable artifact references.

If an immutable artifact, digest, SBOM, provenance record, or source lock is missing, continue repository work. Do not build an ad hoc production release on the target server.

## 8. Phase D — read-only production inventory

Only after `REPOSITORY_PHASE_CERTIFIED=YES` and the immutable release lock is complete, inspect host `49.12.145.107` read-only.

Capture a timestamped, access-restricted, secret-free evidence packet containing:

- hostname, OS/kernel, time sync, uptime, CPU, memory, load, disk, and inodes;
- Docker and Compose versions and daemon health;
- all containers, image IDs/digests, states, health, restarts, networks, mounts, and published ports;
- existing MoneyBee source/release identity;
- current Compose, Caddy, Kong, and environment file paths and checksums;
- environment key names only, file owners, and modes;
- public DNS, redirects, TLS chain/expiry/renewal, CSP/CORS/security headers;
- Keycloak issuer and JWKS reachability plus MoneyBee client IDs/audiences/redirects without secrets;
- PostgreSQL version, extensions, Alembic version, database/schema/table owners, role attributes, connections, size, WAL/PITR/replication, and long-running transactions;
- Redis version, ACL, persistence, memory, and health;
- logs, metrics, dashboards, alerts, backup timers, restore evidence, and rollback release set;
- unexpected source/runtime drift.

Any unexplained drift affecting data, identity, routing, certificates, database ownership, backups, or rollback is NO-GO until reconciled in the repositories or an approved runtime change record.

## 9. Phase E — backup, restore, and rollback proof

Before migration or container replacement:

1. Establish a change ID and freeze schema-changing activity.
2. Create a timestamped PostgreSQL backup.
3. Record the WAL/PITR recovery point when supported.
4. Back up current Compose, route configuration, non-secret configuration, certificate/reference metadata, and all current image digests.
5. Restore the database backup into an isolated disposable database/instance.
6. Verify schema, Alembic version, critical table counts/checksums, and application inspection against the restored copy.
7. Prove the restore does not contact providers or enable external effects.
8. Record backup duration, restore duration, RPO evidence, RTO evidence, and exact rollback commands.
9. Stop if backup or restore validation fails.

## 10. Phase F — production database privilege separation

Use distinct secret-backed roles:

- `moneybee_migrator`: only the migration authority required by the reviewed migrations;
- `moneybee_runtime`: API/worker DML, sequence, and approved function execution only.

Required proof:

```text
RUNTIME_SUPERUSER=NO
RUNTIME_CREATEDB=NO
RUNTIME_CREATEROLE=NO
RUNTIME_REPLICATION=NO
RUNTIME_BYPASSRLS=NO
RUNTIME_SCHEMA_OWNER=NO
RUNTIME_DDL=DENIED
MIGRATOR_AND_RUNTIME_SECRETS_DISTINCT=YES
API_USES_RUNTIME_ROLE=YES
WORKER_USES_RUNTIME_ROLE=YES
MIGRATION_JOB_USES_MIGRATOR_ROLE=YES
```

Do not switch the running application until backup/restore evidence exists and both roles pass connectivity/authorization tests.

## 11. Phase G — fail-closed production configuration

Initial production configuration must include:

```text
APP_ENV=production
AUTO_CREATE_SCHEMA=false
LOCAL_AUTH_BYPASS=false
LOCAL_IDENTITY_ENFORCEMENT=true
OIDC_ISSUER=https://auth.codestra.co/realms/codestra
OIDC_AUDIENCE=moneybee-api
OIDC_ALGORITHMS_CSV=RS256

CODESTRA_SDK_ENABLED=false
CODESTRA_SDK_CAPABILITIES_CSV=
MIDDLEWARE_PROVIDER=disabled
ENABLE_EXTERNAL_DELIVERY=false
LIVE_WRITES=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false

BANK_PROVIDER=disabled
CRM_PROVIDER=disabled
KYB_PROVIDER=disabled
CREDIT_PROVIDER=disabled
LENDER_PROVIDER=disabled
ESIGN_PROVIDER=disabled
EMAIL_PROVIDER=disabled
SMS_PROVIDER=disabled
OBJECT_STORAGE_MODE=disabled
MALWARE_SCAN_PROVIDER=disabled
PAYMENT_PROVIDER=disabled

CREDIT_LIVE_PULL=false
LENDERS_LIVE_SUBMISSION=false
ESIGN_LIVE_SEND=false
FUNDING_LIVE_CONFIRMATION=false
PAYMENTS_ENABLED=false
PAYOUTS_ENABLED=false
TAX_FILING_ENABLED=false
COMMUNICATIONS_LIVE_EMAIL=false
COMMUNICATIONS_LIVE_SMS=false

BACKUP_STATUS=PASS
RESTORE_STATUS=PASS
STAGING_STATUS=PASS
SOURCE_SHA=<exact backend merge SHA>
MIGRATION_HEAD=20260901_0026
CONFIGURATION_CHECKSUM=<verified checksum>
BACKUP_REFERENCE=<verified backup reference>
```

Production CORS origins:

```text
https://moneybeeloan.com
https://www.moneybeeloan.com
https://app.moneybeeloan.com
https://lenders.moneybeeloan.com
https://admin.moneybeeloan.com
```

Secrets must come from the approved secret store or restricted root-owned files. Run the repository environment and release-lock validators before Compose. One failure is NO-GO.

## 12. Phase H — exact-release staging rehearsal

Deploy the exact production digests and configuration shape to staging first with all external effects disabled.

Required staging evidence:

- restore a production-like backup copy;
- one-shot migration using `moneybee_migrator`;
- API/worker runtime using `moneybee_runtime`;
- `/health/live` and `/health/ready`;
- exact source/image/config identity;
- OpenAPI and endpoint catalog alignment;
- borrower/lender/admin Keycloak client and tenant separation;
- public product and intake flows without external delivery;
- application resume/status/offer/disclosure/compliance flows;
- idempotent replay and altered-request conflict behavior;
- PostgreSQL concurrent command tests;
- ambiguous provider-outcome/read-back/no-repeat simulations;
- finance double-entry and runtime DDL-denial behavior;
- all four frontend builds, routes, deep links, responsive layouts, and accessibility smoke;
- Caddy/Kong routing, HTTPS, CSP/CORS/headers, request/correlation IDs, logs, metrics, and alerts;
- rollback to the prior staging release and successful re-forward.

`STAGING_STATUS=PASS` must identify the same source SHAs and image digests intended for production.

## 13. Phase I — production installation and write-disabled go-live

1. Create a new immutable release directory. Do not edit the current release in place.
2. Place only reviewed Compose, lock, and configuration references there.
3. Pull all images by digest and verify the pulled digests.
4. Verify backup, restore, release lock, configuration checksum, database role separation, and rollback command again.
5. Run the migrator image once using `moneybee_migrator`.
6. Verify Alembic head `20260901_0026` and no unexpected schema drift.
7. Start API and worker using `moneybee_runtime` with all providers/effects disabled.
8. Start marketing, borrower, lender, and administrator frontends.
9. Apply reviewed Caddy/Kong routing atomically with immediate rollback to the prior upstream set.
10. Configure/verify canonical public surfaces:

```text
https://moneybeeloan.com
https://www.moneybeeloan.com
https://app.moneybeeloan.com
https://lenders.moneybeeloan.com
https://admin.moneybeeloan.com
https://api.moneybeeloan.com/api/v2
https://auth.codestra.co/realms/codestra
```

11. Do not route public traffic until direct upstream health, source SHA, digest, migration, identity, and database-role assertions pass.
12. Shift traffic through a controlled canary.
13. Monitor error rate, latency, container restarts, database load, Redis, logs, metrics, and alerts.
14. Confirm no provider or external-effect action occurred.

## 14. Phase J — production acceptance

Verify from inside and outside the host:

- DNS and intended host authority;
- TLS hostname, chain, expiry, renewal;
- HTTP-to-HTTPS and canonical redirects;
- CSP, HSTS, CORS, cookies, and security headers;
- exact backend/frontend source and image identities;
- container health and restart counts;
- API/worker non-DDL database role;
- exact Alembic head;
- PostgreSQL and Redis readiness;
- Keycloak issuer, audience, client, redirect, login, logout, and portal separation;
- cross-tenant and cross-portal denial;
- public site, borrower, lender, admin routes, assets, deep links, mobile, and accessibility;
- compliance audit/idempotency/TIN/disclosure behavior;
- finance and reconciliation read-back behavior;
- request/correlation IDs in logs without secrets;
- metrics, dashboards, and alert delivery;
- truthful provider/capability disabled state;
- immediate rollback availability.

The initial accepted state is:

```text
SOFTWARE_LIVE=YES
PUBLIC_HTTPS_LIVE=YES
IDENTITY_LIVE=YES
CORE_DATABASE_LIVE=YES
OBSERVABILITY_LIVE=YES
ROLLBACK_READY=YES

EXTERNAL_DELIVERY=DISABLED
CREDIT_PULL=DISABLED
LENDER_SUBMISSION=DISABLED
ESIGN_SEND=DISABLED
FUNDING=DISABLED
PAYMENT=DISABLED
PAYOUT=DISABLED
TAX_FILING=DISABLED
EMAIL=DISABLED
SMS=DISABLED
ODOO_WRITE=DISABLED
N8N_DELIVERY=DISABLED
CODESTRA_SDK_COMMANDS=DISABLED
```

Declare the platform `LIVE_WITH_EXTERNAL_EFFECTS_DISABLED`, not fully provider-live.

## 15. Separate capability activation

Each provider/effect requires its own reviewed mission, credential/network readiness, sandbox evidence, idempotency/reconciliation, monitoring, rollback, and explicit approval. Activate one capability at a time.

Recommended order:

1. read-only provider health;
2. object storage and malware scanning with fixtures;
3. Codestra event delivery to the dedicated Middleware ingress;
4. Odoo CRM projection through Middleware/SDK;
5. email/SMS sandbox and suppression/bounce handling;
6. banking sandbox and webhooks;
7. KYB, credit, lender, and e-sign sandbox certification;
8. payment/funding only under a separate financial-production mission.

Never infer live-write approval from configured credentials or successful health checks.

## 16. Mandatory rollback triggers

Rollback or stop immediately on:

- ungreen repository or mismatched source SHA;
- missing/invalid digest, SBOM, provenance, or release lock;
- failed backup or restore;
- migration error or unexpected schema drift;
- wrong Keycloak issuer/audience/client/redirect;
- runtime database DDL/admin rights;
- cross-tenant or cross-portal access;
- repeated restarts or failed readiness;
- material error/latency regression;
- missing logs, metrics, or alerts during cutover;
- secret exposure;
- unexpected provider call, external message, lender submission, filing, payment, payout, funding, Odoo write, n8n execution, or SDK command;
- ambiguous consequential operation without durable read-back/reconciliation.

Do not simply restart an older application image against an incompatible schema. Use the verified recovery point or an approved forward fix.

## 17. Required Codex reporting

Post repository progress to PR #42, frontend PR #27, and issue #44. At completion return one evidence packet:

```text
MISSION_ID=MONEYBEE_REPOSITORY_TO_PRODUCTION_2026_09_02

BACKEND_FINAL_HEAD=
BACKEND_MAIN_MERGE_SHA=
BACKEND_CI_RUNS=
BACKEND_TEST_RESULT=
BACKEND_OPENAPI_DIGEST=
BACKEND_ENDPOINT_CATALOG_DIGEST=
ALEMBIC_HEAD=

FRONTEND_FINAL_HEAD=
FRONTEND_MAIN_MERGE_SHA=
FRONTEND_BACKEND_CONTRACT_SHA=
FRONTEND_CI_RUN=
FRONTEND_CONTRACT_ARTIFACT_DIGEST=

SDK_SHA=
IMAGE_DIGESTS=
SBOM_DIGESTS=
PROVENANCE_DIGESTS=
COMPOSE_CHECKSUMS=
CONFIGURATION_CHECKSUM=
RELEASE_LOCK_COMMIT=

REPOSITORY_PHASE_CERTIFIED=
SERVER_PREFLIGHT=
BACKUP_REFERENCE=
BACKUP_RESULT=
RESTORE_RESULT=
RPO_EVIDENCE=
RTO_EVIDENCE=
DATABASE_ROLE_SEPARATION=
MIGRATION_RESULT=
DEPLOYED_RELEASE_DIRECTORY=
DEPLOYED_IMAGE_DIGESTS=
DNS_TLS_RESULT=
KEYCLOAK_RESULT=
TENANCY_NEGATIVE_TESTS=
API_SMOKE=
FRONTEND_SMOKE=
OBSERVABILITY_RESULT=
EXTERNAL_EFFECTS_OBSERVED=
ROLLBACK_REHEARSAL=

INITIAL_PRODUCTION_STATE=LIVE_WITH_EXTERNAL_EFFECTS_DISABLED
GO_NO_GO=
REMAINING_BLOCKERS=
```

No `PASS`, `CERTIFIED`, `LIVE`, or `GO` value may be reported without matching inspectable evidence.
