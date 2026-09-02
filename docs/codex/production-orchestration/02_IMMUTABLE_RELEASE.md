# Phase 02 — Immutable artifacts, source locks and release certification

Phase ID: `MONEYBEE_PHASE_02_RELEASE`

Predecessor: Phase 01 `GO`.

Production server contact: **forbidden until this phase exits `GO`**.

## Objective

Turn the protected backend, frontend and supporting-repository merge SHAs into one complete, reproducible, immutable release. Publish digest-pinned images and a fail-closed release lock that a server can verify without interpreting moving branches or mutable tags.

## 1. Choose the runtime authority

Use `appolon1908-hue/codestra-production-runtime-authority` as the planned production release/runtime authority after inspecting its README, governance, current branch, open PRs and existing source locks. If another existing repository is already the documented authority, preserve that authority and record the decision in issue #44.

Shared infrastructure evidence may also be recorded in `appolon1908-hue/Infustruction-repo`, but there must be one principal release lock. Conflicting locks are a `NO_GO`.

## 2. Record source authorities

The release candidate must lock at least:

```text
Moneybee-Backend protected main merge SHA
Moneybee-frontend- protected main merge SHA
SDK-repository SHA
Keycloak SHA when MoneyBee identity config changes
Kong SHA when MoneyBee routes/plugins change
Caddy SHA when MoneyBee hosts/TLS change
Middleware- SHA when MoneyBee integration commands/events change
Odoo SHA when MoneyBee CRM/module mappings change
N8N SHA when MoneyBee workflows change
Codestra-OpenBao SHA when secret policy/config changes
runtime authority SHA
shared infrastructure SHA
observability repository SHAs for every changed rule/dashboard/scrape/probe/alert
Alembic head
OpenAPI checksum
endpoint-catalog checksum
frontend/backend contract checksum
```

The lock must not contain an unresolved branch reference where an exact commit is required.

## 3. Build outside the production host

Build in GitHub Actions or another reviewed build runner—not on `49.12.145.107`.

Required components:

```text
moneybee-api
moneybee-worker
moneybee-migrate
moneybee-marketing
moneybee-borrower
moneybee-lender
moneybee-admin
```

For each image:

- checkout the exact protected merge SHA;
- verify `git rev-parse HEAD`;
- use the reviewed Dockerfile and a deterministic dependency lock;
- set OCI source, revision, created-time and component labels;
- run repository tests before publishing;
- build as an unprivileged runtime where appropriate;
- do not embed Git credentials, tokens, provider secrets, `.env` files, test databases or source-control metadata;
- publish to GHCR or the approved registry;
- resolve and record the immutable `sha256:` manifest digest;
- retain build logs and workflow/run identifiers.

Tags may exist for human navigation, but deployment uses only digests.

## 4. Security and supply-chain evidence

For every image and release artifact:

```text
HIGH_CRITICAL_VULNERABILITY_POLICY=PASS
DEPENDENCY_CHECK=PASS
PRIVATE_KEY_AND_SECRET_SCAN=PASS
SBOM_GENERATED=PASS
SBOM_DIGEST_RECORDED=PASS
PROVENANCE_ATTESTATION=PASS
PROVENANCE_DIGEST_RECORDED=PASS
IMAGE_SIGNATURE_OR_APPROVED_ATTESTATION=PASS
OCI_SOURCE_LABEL=PASS
OCI_REVISION_LABEL=PASS
NONROOT_RUNTIME=PASS_WHERE_APPLICABLE
NO_GIT_RUNTIME_DEPENDENCY=PASS
```

Unfixed vulnerability exceptions require an explicit reviewed allowlist with package/CVE, reason, compensating control, expiry and owner. A blanket ignore is prohibited.

## 5. Render deployment configuration

From the runtime authority repository, render the complete production configuration without secrets and calculate checksums for:

- Compose/Kubernetes/other runtime manifests;
- Caddy configuration;
- Kong declarative or Admin API plan;
- Keycloak realm/client/role plan;
- application environment schema and safety flags;
- network topology;
- volume and backup map;
- PostgreSQL role/grant plan;
- observability scrape, dashboard, log, trace, probe and alert configuration;
- rollback configuration.

Every image reference in the rendered production manifest must use an immutable digest. `latest` and floating semver tags are forbidden.

## 6. Complete release lock

Create a machine-readable release lock similar to:

```json
{
  "release_id": "moneybee-<UTC timestamp>-<short source sha>",
  "status": "REPOSITORY_PHASE_CERTIFIED",
  "deployment_authorized": true,
  "target_host": "49.12.145.107",
  "sources": {
    "backend": "<sha>",
    "frontend": "<sha>",
    "sdk": "<sha>",
    "runtime_authority": "<sha>"
  },
  "images": {
    "api": "ghcr.io/...@sha256:<digest>",
    "worker": "ghcr.io/...@sha256:<digest>",
    "migrate": "ghcr.io/...@sha256:<digest>",
    "marketing": "ghcr.io/...@sha256:<digest>",
    "borrower": "ghcr.io/...@sha256:<digest>",
    "lender": "ghcr.io/...@sha256:<digest>",
    "admin": "ghcr.io/...@sha256:<digest>"
  },
  "alembic_head": "20260901_0026",
  "configuration_checksum": "sha256:<digest>",
  "openapi_checksum": "sha256:<digest>",
  "endpoint_catalog_checksum": "sha256:<digest>",
  "sboms": {},
  "provenance": {},
  "rollback": {},
  "initial_capabilities": {
    "external_effects": false
  }
}
```

The real lock must contain complete values, not placeholders.

## 7. Release-lock verifier

Provide a read-only verifier that fails when:

- a required field is absent;
- a source SHA is not 40 hexadecimal characters;
- an image is not digest-pinned;
- duplicate/conflicting component authorities exist;
- the frontend contract SHA differs from the backend SHA;
- the migration head differs from the backend code head;
- checksums or signatures do not verify;
- an initial live-effect flag is enabled;
- the rollback set is incomplete;
- the target host differs from the approved host.

Run this verifier in CI and again before any server command.

## 8. Release rollback set

Record the previous known-good immutable release, including:

- all prior image digests;
- previous runtime configuration checksum;
- previous Keycloak/Kong/Caddy plans or exact source SHAs;
- compatible database schema range;
- database backup reference required before migration;
- rollback commands and decision authority.

If the new migration is not safely application-rollback-compatible, define forward-recovery or database-restore policy explicitly. Do not claim rollback by merely retaining an old image.

## 9. Publish repository-phase certification

Create and merge through normal review a repository certification record containing:

```text
RELEASE_ID
BACKEND_MERGE_SHA
FRONTEND_MERGE_SHA
SUPPORTING_REPOSITORY_SHAS
ALEMBIC_HEAD
IMAGE_DIGESTS
SBOM_DIGESTS
PROVENANCE_REFERENCES
OPENAPI_CHECKSUM
ENDPOINT_CATALOG_CHECKSUM
CONFIGURATION_CHECKSUM
ROLLBACK_SET
WORKFLOW_RUNS
OPEN_REVIEW_FINDINGS=0
INITIAL_EXTERNAL_EFFECTS=DISABLED
```

Update `deploy/repository-source.lock.json` or supersede it with the final complete lock. The old blocked candidate values must not remain presented as deployable authority.

## Exit gate

Phase 02 is `GO` only when:

```text
REPOSITORY_PHASE_CERTIFIED=YES
PROTECTED_MAIN_SHAS_LOCKED=YES
ALL_SEVEN_IMAGE_DIGESTS_RECORDED=YES
ALL_IMAGE_SCANS=PASS
ALL_SBOMS_AND_PROVENANCE_RECORDED=YES
CONFIGURATION_CHECKSUM_RECORDED=YES
ROLLBACK_SET_COMPLETE=YES
RELEASE_LOCK_VERIFIER=PASS
INITIAL_EXTERNAL_EFFECTS=DISABLED
SERVER_CONTACT_AUTHORIZED=YES
```

A failure means `PHASE_02_NO_GO`. Continue repository/build remediation; do not access or mutate the production host.
