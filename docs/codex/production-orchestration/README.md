# MoneyBee continuous repository-to-production orchestration

Mission ID: `MONEYBEE_CONTINUOUS_REPOSITORY_TO_PRODUCTION_2026_09_02`

Target production host: `49.12.145.107`

Execution authority:

- master execution issue: `appolon1908-hue/Moneybee-Backend#44`;
- mission pull request: `appolon1908-hue/Moneybee-Backend#45`;
- backend release pull request: `appolon1908-hue/Moneybee-Backend#42`;
- frontend release pull request: `appolon1908-hue/Moneybee-frontend-#27`;
- original full mission: `docs/codex/CODEX_MONEYBEE_REPOSITORY_TO_PRODUCTION_MISSION_2026-09-02.md`;
- fail-closed source lock: `deploy/repository-source.lock.json`.

This directory divides the full mission into coordinated execution packets. Codex must execute the packets in dependency order, continuously remediate failed gates, keep the repositories and runtime synchronized, and publish inspectable evidence after every phase.

## Current starting state

```text
BACKEND_REPOSITORY=appolon1908-hue/Moneybee-Backend
BACKEND_MAIN_AT_PUBLICATION=aa6a8413b79885c499482b53e0c3ffaf8637c9d4
BACKEND_RELEASE_PR=42
BACKEND_RELEASE_BRANCH=release/moneybee-repository-complete-20260902
BACKEND_RELEASE_HEAD=b8682c4542738caae9f58c00f628a7f74dccfb10
BACKEND_EXACT_HEAD_RESULT=4_FAILED_277_PASSED

FRONTEND_REPOSITORY=appolon1908-hue/Moneybee-frontend-
FRONTEND_MAIN_AT_PUBLICATION=b40d519ccc4318f0525171b1d71f64176daabbd2
FRONTEND_RELEASE_PR=27
FRONTEND_RELEASE_BRANCH=release/moneybee-frontend-repository-complete-20260902
FRONTEND_RELEASE_HEAD=7058cd7c49b59931bc8c462e721511fd0b77f012
FRONTEND_LAST_BACKEND_CONTRACT=bb5e00016be80c036500fb8cb382b3c47fd88c9b

CONNECTOR_SDK_REPOSITORY=appolon1908-hue/SDK-repository
CONNECTOR_SDK_SHA=fd9a5c3fd49534a7f7492a452f53815c386687b9
ALEMBIC_HEAD=20260901_0026
REPOSITORY_PHASE_CERTIFIED=NO
SERVER_CONTACT_AUTHORIZED=NO
DEPLOYMENT_AUTHORIZED=NO
```

The exact branch heads must be rediscovered before work begins. Never assume the publication values are still current.

## Continuous-execution rule

Codex must not stop after writing a plan, identifying the first defect, fixing only one test, producing local-only work, or reaching a failed CI run. It must:

1. inspect the authoritative repository and current review evidence;
2. implement the required repair in the owning repository;
3. add or strengthen regression tests;
4. run the complete repository-native gate;
5. push the logical commit to the active review branch;
6. inspect the resulting exact-head CI and review feedback;
7. repeat until the phase exit gate is satisfied;
8. hand off the exact immutable evidence to the next phase.

A failed gate does not authorize bypass. It means remediate and rerun.

## Non-bypass rule

Continuous execution does **not** authorize bypassing or disabling:

- branch protection, required reviews, required status checks, merge queues, signed-release policy, or exact-head validation;
- tenant/resource authorization, portal-client separation, idempotency, audit, reconciliation, rate limits, secret redaction, or provider capability gates;
- database backup, isolated restore, migration, runtime DDL denial, health/readiness, observability, canary, or rollback gates;
- SSH key policy, `authorized_keys`, `sshd_config`, sudo rules, SSH users, or SSH firewall rules;
- the fail-closed source/release lock.

When a safety gate blocks a production mutation, Codex must stop that mutation, preserve evidence, continue safe repository remediation and read-only diagnosis, and resume from the failed gate after the owning fix is reviewed and released.

## Repository authority matrix

Every durable change belongs in an owning repository. No production-only patch is allowed.

| Concern | Planned authority |
| --- | --- |
| MoneyBee API, workers, migrations and domain contracts | `appolon1908-hue/Moneybee-Backend` |
| Marketing, borrower, lender and administrator applications | `appolon1908-hue/Moneybee-frontend-` |
| MoneyBee/Codestra connector package | `appolon1908-hue/SDK-repository` |
| OIDC realm, clients, roles, scopes and service accounts | `appolon1908-hue/Keycloak` |
| API gateway services, routes, plugins and upstream policy | `appolon1908-hue/Kong` |
| Public hostnames, TLS and edge reverse-proxy policy | `appolon1908-hue/Caddy` |
| Codestra integration command/event plane | `appolon1908-hue/Middleware-` |
| ERP/CRM mappings and MoneyBee modules | `appolon1908-hue/Odoo` |
| Automation workflows and callback bindings | `appolon1908-hue/N8N` |
| Production release/runtime source lock | `appolon1908-hue/codestra-production-runtime-authority` |
| Shared infrastructure and host evidence | `appolon1908-hue/Infustruction-repo` |
| Secret-management configuration | `appolon1908-hue/Codestra-OpenBao` |
| Metrics and rules | `appolon1908-hue/Codestra-Prometheus` |
| Dashboards | `appolon1908-hue/Codestra-Grafana-` |
| Logs | `appolon1908-hue/Codestra-Loki` |
| Traces | `appolon1908-hue/Codestra-Tempo` |
| Host/container telemetry shipping | `appolon1908-hue/Codestra-Alloy`, `Codestra-Node-Exporter`, `Codestra-cAdvisor` |
| Synthetic endpoint probes | `appolon1908-hue/Codestra-Blackbox-Exporter` |
| Alert routing | `appolon1908-hue/Codestra-Alertmanager` |

Before changing a supporting repository, inspect its README, AGENTS instructions, current protected branch, open PRs, release workflow, and production authority records. If an existing authority conflicts with this planned mapping, preserve the established authority and record the decision in the master issue and release lock.

## Phase dependency graph

```text
01 Repository completion and protected merges
   -> 02 Immutable artifacts and complete release lock
      -> 03 Server discovery, backup, restore and database authority
         -> 04 Installation, identity, ingress and core runtime
            -> 05 Integration synchronization and end-to-end validation
               -> 06 Write-disabled production canary, observability and rollback
                  -> 07 Final certification and capability activation queue
```

Codex may prepare repository changes for later phases in parallel, but it must not execute a production mutation before all predecessor exit gates pass.

## Public production surfaces

```text
https://moneybeeloan.com
https://www.moneybeeloan.com
https://app.moneybeeloan.com
https://lenders.moneybeeloan.com
https://admin.moneybeeloan.com
https://api.moneybeeloan.com/api/v2
OIDC issuer: https://auth.codestra.co/realms/codestra
```

The runtime must expose only the intended public surfaces. PostgreSQL, Redis, workers, migrations, OpenBao, Odoo, n8n, metrics backends and internal integration endpoints remain private unless an existing reviewed architecture explicitly requires protected exposure.

## Release components

The immutable release set must include:

```text
moneybee-api
moneybee-worker
moneybee-migrate
moneybee-marketing
moneybee-borrower
moneybee-lender
moneybee-admin
```

Every component must be identified by repository, exact source SHA, immutable image digest, build workflow/run, SBOM digest, provenance/attestation reference, vulnerability result, configuration checksum and rollback image digest.

## Initial production capability state

The first successful production state is core software live with external effects disabled:

```text
SOFTWARE_LIVE=true
IDENTITY_LIVE=true
CORE_DATABASE_LIVE=true
READ_ONLY_AND_INTERNAL_DOMAIN_WORKFLOWS_AVAILABLE=true

CODESTRA_SDK_ENABLED=false
MIDDLEWARE_PROVIDER=disabled
ENABLE_EXTERNAL_DELIVERY=false
LIVE_WRITES=false
ODOO_WRITE=false
N8N_DELIVERY=false
BANK_PROVIDER=disabled
KYB_PROVIDER=disabled
CREDIT_PROVIDER=disabled
LENDER_PROVIDER=disabled
ESIGN_PROVIDER=disabled
EMAIL_PROVIDER=disabled
SMS_PROVIDER=disabled
OBJECT_STORAGE_MODE=disabled
MALWARE_SCAN_PROVIDER=disabled
PAYMENT_PROVIDER=disabled
LIVE_FUNDING=false
LIVE_PAYOUTS=false
TAX_FILING=false
LIVE_DIALING=false
```

No phase may silently convert a disabled capability into a live effect. Every later capability activation requires its own source change or approved runtime change, evidence, rollback, owner authorization and post-activation monitoring.

## Coordination and evidence rules

For every phase, Codex must post an evidence update to:

1. backend PR #42 while backend work is active;
2. frontend PR #27 while frontend work is active;
3. mission PR #45;
4. master issue #44;
5. the PR in every supporting repository changed by the phase.

Every update must include exact repository SHA, changed files, commands/gates, test counts, workflow links, artifact digests, unresolved findings and a phase `GO` or `NO_GO`. A claim is not evidence without an inspectable source.

## Hard-stop conditions

Production mutation is prohibited when any of the following is true:

- Codex cannot access the required repository environment;
- a required review finding remains open;
- exact-head CI is absent, stale, cancelled or failed;
- a source SHA, image digest or configuration checksum does not match the release lock;
- a secret is found in Git, image layers, logs, command arguments or evidence;
- backup or isolated restore fails;
- database role separation or runtime DDL denial fails;
- migration head or schema state is ambiguous;
- identity, tenant, portal-client or authorization checks fail;
- an external effect is enabled during the initial release;
- a consequential provider outcome is ambiguous without durable reconciliation;
- health/readiness, monitoring, alerts, canary or rollback proof fails;
- server/runtime drift cannot be traced to an owning repository.

Do not bypass these conditions. Repair the owning repository or configuration, rebuild the immutable artifact, update the lock, rerun the failed phase and continue.

## Final required outcome

```text
BACKEND_MAIN_CERTIFIED=YES
FRONTEND_MAIN_CERTIFIED=YES
SUPPORTING_REPOSITORIES_LOCKED=YES
IMMUTABLE_RELEASE_PUBLISHED=YES
BACKUP_VERIFIED=YES
ISOLATED_RESTORE_VERIFIED=YES
DATABASE_ROLE_SEPARATION=PASS
MIGRATION_ONE_SHOT=PASS
PRODUCTION_INSTALLATION=PASS
HTTPS_AND_IDENTITY=PASS
API_AND_ALL_FRONTENDS=PASS
TENANT_AND_PORTAL_ISOLATION=PASS
INTEGRATION_SYNC_WRITE_DISABLED=PASS
OBSERVABILITY_AND_ALERTING=PASS
CANARY=PASS
ROLLBACK_PROOF=PASS
PRODUCTION_STATE=LIVE_WITH_EXTERNAL_EFFECTS_DISABLED
```

Only after that outcome may separately approved capability-activation missions begin.
