# Phase 01 — Repository completion and protected merges

Phase ID: `MONEYBEE_PHASE_01_REPOSITORIES`

Predecessor: none.

Production server contact: **forbidden**.

## Objective

Produce one reviewed, exact-head-green backend `main` and one reviewed, exact-head-green frontend `main`, with the frontend contract locked to the final backend merge SHA. Consolidate all required MoneyBee work into those authoritative lineages before building a release.

## 1. Re-discover authority

Before editing, record:

```text
backend main SHA
backend PR #42 head SHA and base SHA
backend PR #42 review threads and required checks
frontend main SHA
frontend PR #27 head SHA and base SHA
frontend PR #27 review threads and required checks
mission PR #45 head SHA
all open MoneyBee backend/frontend PRs
SDK-repository pinned SHA
Alembic heads
```

Inspect every open MoneyBee PR. Required work must be included in PR #42 or PR #27, merged earlier into their bases, or explicitly excluded with evidence. Do not leave a production-critical API, endpoint, migration, UI flow, security correction or deployment manifest stranded in an unrelated branch.

## 2. Complete backend PR #42

Starting known failures at publication:

1. legacy commercial-financing disclosure acknowledgment returns success without the required durable audit record;
2. concurrent tax-filing requests with the same idempotency identity can race into `uq_idempotency_actor_route_key` and expose an integrity error;
3. a DocuSign void accepted upstream with a lost response is not reconciled by provider read-back before the local transition;
4. an unresolved void returns generic `REQUEST_FAILED` instead of `CONTRACT_VOID_RECONCILIATION_REQUIRED` and does not preserve safe no-repeat evidence.

Required behavior:

### Legacy disclosure acknowledgment

- Route the compatibility path through the audited domain command.
- Preserve compatibility if the legacy endpoint historically omitted `Idempotency-Key`, but derive a deterministic server-side idempotency identity and document it.
- Create exactly one `COMMERCIAL_FINANCING_DISCLOSURE_ACKNOWLEDGED` audit event.
- Create exactly one durable idempotency record.
- Attribute the authenticated principal, never a client-supplied actor.
- Same request replay returns the original response and creates no duplicate effect.
- Cross-tenant or unauthorized access remains denied.

### Concurrent tax filing evidence

- Serialize or atomically reserve the idempotency identity before applying the domain effect.
- Recheck idempotency after acquiring any row/advisory lock.
- Same actor/route/key/request returns one durable result under concurrency.
- Same key with a changed normalized request returns the canonical conflict.
- No raw `IntegrityError`, SQL text or database constraint name may reach the client.
- The filing record, audit event and idempotency evidence commit atomically.

### Ambiguous DocuSign void

- Make at most one consequential upstream void attempt for one operation identity.
- On timeout/lost response, record the ambiguous attempt and perform provider read-back.
- If read-back proves `voided`, transition the local contract once and persist evidence.
- If read-back is unavailable or inconclusive, persist reconciliation-required/no-repeat evidence and return `CONTRACT_VOID_RECONCILIATION_REQUIRED`.
- A later automated retry must not repeat the void blindly.
- A controlled reconciliation command may read provider status and close the operation.
- Provider remains disabled by default; tests use fakes and do not contact DocuSign.

### Broader backend review

Inspect and repair related defects in:

- audit/idempotency transaction boundaries;
- tenant/resource and portal-client authorization;
- sensitive-data redaction;
- capability fail-closed behavior;
- provider timeout/unknown-outcome handling;
- migration safety and one-head topology;
- OpenAPI operation IDs, response models and additive manifests;
- endpoint catalog generation;
- SDK exact-SHA and runtime wheelhouse behavior;
- API/worker runtime DDL denial;
- release Compose and configuration locks.

Do not weaken or delete tests to obtain green CI.

## 3. Backend exact-head gates

All gates must run on one unchanged PR head:

```text
GIT_DIFF_CHECK=PASS
DEPENDENCY_INSTALL_AND_PIP_CHECK=PASS
RUFF=PASS
FORMAT_CHECK=PASS_WHERE_CONFIGURED
COMPILEALL=PASS
PRIVATE_KEY_AND_SECRET_SCAN=PASS
ALEMBIC_SINGLE_HEAD=PASS
POSTGRES_EMPTY_TO_HEAD=PASS
MIGRATION_DOWNGRADE_REUPGRADE=PASS
RUNTIME_DDL_DENIAL=PASS
IDENTITY_TENANCY=PASS
PORTAL_CLIENT_ISOLATION=PASS
IDEMPOTENCY_RACES=PASS
AUDIT_EVIDENCE=PASS
PROVIDER_AMBIGUOUS_OUTCOMES=PASS
FULL_PYTEST=PASS
OPENAPI_DRIFT=PASS
ENDPOINT_CATALOG_DRIFT=PASS
API_SMOKE=PASS
API_IMAGE_BUILD_SCAN=PASS
WORKER_IMAGE_BUILD_SCAN=PASS
MIGRATOR_IMAGE_BUILD_SCAN=PASS
SBOM=PASS
SECURE_SCAFFOLD_CI=PASS
BACKEND_CI=PASS
CODE_REVIEW=PASS
OPEN_REVIEW_FINDINGS=0
```

Post the exact final head and workflow links to backend PR #42 and issue #44.

## 4. Protected backend merge

Merge backend PR #42 only through the repository's normal protected controls. Do not dismiss valid reviews, disable rules, override failed checks, or merge a stale head.

After merge:

- fetch protected `main`;
- record the exact backend merge SHA;
- rerun required post-merge workflows if repository policy requires them;
- verify the committed OpenAPI, endpoint catalog and migration head at that SHA;
- mark all superseded backend PRs with traceability and close only when their required content is present in `main`.

Set:

```text
BACKEND_MAIN_CERTIFIED=YES
BACKEND_MERGE_SHA=<exact 40-character SHA>
```

## 5. Complete frontend PR #27

The frontend must be updated **after** the backend merge SHA is final.

Required changes:

- replace any branch/tag/old commit contract reference with the exact backend merge SHA;
- checkout that SHA in normal CI and assert `git rev-parse HEAD`;
- export runtime OpenAPI from that exact backend checkout;
- regenerate or align typed clients and route contracts;
- fix every valid Codex review finding, including known pagination and partial-read behavior;
- preserve successful compliance sections when one independent endpoint fails;
- expose pagination or complete bounded loading for notices, disclosures and tax records;
- preserve authoritative decimal/legal values from the backend;
- preserve write-only TIN behavior;
- keep provider/database/service credentials out of browser source, builds and artifacts;
- verify protected deep links, tenant context, token lifecycle, URI encoding, offline/ambiguous mutation behavior, accessibility, mobile responsiveness and CSP/security boundaries.

Inspect all other open frontend PRs and ensure their required production work is integrated or explicitly excluded.

## 6. Frontend exact-head gates

All gates must run on one unchanged frontend PR head and exact backend merge SHA:

```text
FROZEN_DEPENDENCY_INSTALL=PASS
BACKEND_SHA_ASSERTION=PASS
RUNTIME_OPENAPI_EXPORT=PASS
FRONTEND_BACKEND_ROUTE_DRIFT=PASS
GENERATED_CLIENT_DRIFT=PASS_IF_APPLICABLE
TYPESCRIPT=PASS
UNIT_AND_COMPONENT_TESTS=PASS
MARKETING_BUILD=PASS
BORROWER_BUILD=PASS
LENDER_BUILD=PASS
ADMIN_BUILD=PASS
FRONTEND_SCAFFOLD_VALIDATION=PASS
ACCESSIBILITY_CHECKS=PASS
RESPONSIVE_AND_PROTECTED_ROUTE_CHECKS=PASS
NO_DIRECT_PROVIDER_OR_DATABASE_ACCESS=PASS
NO_BROWSER_SECRET=PASS
MARKETING_IMAGE_BUILD_SCAN=PASS
BORROWER_IMAGE_BUILD_SCAN=PASS
LENDER_IMAGE_BUILD_SCAN=PASS
ADMIN_IMAGE_BUILD_SCAN=PASS
CONTRACT_EVIDENCE_ARTIFACT=PASS
SECURE_FRONTEND_CI=PASS
CODE_REVIEW=PASS
OPEN_REVIEW_FINDINGS=0
```

## 7. Protected frontend merge

Merge frontend PR #27 only through normal protected controls after it is locked to the final backend merge SHA and every exact-head gate passes.

After merge:

- fetch protected frontend `main`;
- record the exact frontend merge SHA;
- rerun required post-merge workflows;
- verify all four applications build from that SHA;
- verify the frontend contract lock references the exact backend merge SHA.

Set:

```text
FRONTEND_MAIN_CERTIFIED=YES
FRONTEND_MERGE_SHA=<exact 40-character SHA>
FRONTEND_BACKEND_CONTRACT_SHA=<BACKEND_MERGE_SHA>
```

## 8. Supporting repository changes

If the final MoneyBee contract requires changes to SDK, Keycloak, Kong, Caddy, Middleware, Odoo, N8N, OpenBao, runtime authority, infrastructure or observability repositories:

1. create a focused branch in the owning repository;
2. add implementation, tests/config validation, documentation and rollback evidence;
3. open a PR;
4. pass that repository's protected checks and review;
5. merge normally;
6. record the exact merge SHA for Phase 02.

Do not patch the production host to compensate for a missing repository change.

## Exit gate

Phase 01 is `GO` only when:

```text
BACKEND_MAIN_CERTIFIED=YES
FRONTEND_MAIN_CERTIFIED=YES
FRONTEND_BACKEND_CONTRACT_SHA=BACKEND_MERGE_SHA
ALL_REQUIRED_SUPPORTING_REPO_PRS_MERGED=YES
OPEN_CRITICAL_OR_HIGH_REVIEW_FINDINGS=0
REPOSITORY_WORKTREES_CLEAN=YES
```

Otherwise report `PHASE_01_NO_GO`, preserve exact evidence, continue repository remediation, and do not contact the production host.
