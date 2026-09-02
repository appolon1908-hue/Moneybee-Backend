# Phase 07 — Final certification and controlled capability activation queue

Phase ID: `MONEYBEE_PHASE_07_CERTIFICATION`

Predecessor: Phase 06 `GO`.

## Objective

Publish one final, inspectable certification packet for the live write-disabled MoneyBee platform and create a separately governed activation queue for external providers and business effects. Do not bundle provider activation into the core production declaration.

## 1. Final certification packet

Create a durable report in the production runtime authority and link it from issue #44 and mission PR #45.

The report must include:

```text
MISSION_ID
CHANGE_ID
TARGET_HOST
RELEASE_ID
PRODUCTION_DECLARATION_UTC
BACKEND_REPOSITORY_AND_MERGE_SHA
FRONTEND_REPOSITORY_AND_MERGE_SHA
SDK_REPOSITORY_AND_SHA
ALL_CHANGED_SUPPORTING_REPOSITORY_SHAS
ALL_INSTALLED_IMAGE_DIGESTS
OCI_SOURCE_AND_REVISION_LABELS
ALEMBIC_HEAD
OPENAPI_CHECKSUM
ENDPOINT_CATALOG_CHECKSUM
FRONTEND_CONTRACT_CHECKSUM
RUNTIME_CONFIGURATION_CHECKSUM
CADDY_CHECKSUM
KONG_CHECKSUM
KEYCLOAK_PLAN_CHECKSUM
OPENBAO_POLICY_CHECKSUM
OBSERVABILITY_CONFIGURATION_SHAS
BACKUP_REFERENCE_AND_CHECKSUM
ISOLATED_RESTORE_RESULT_AND_RTO_RPO
DATABASE_ROLE_AND_DDL_DENIAL_RESULT
IDENTITY_TENANCY_PORTAL_ISOLATION_RESULT
API_AND_ALL_FRONTEND_RESULTS
INTEGRATION_SYNC_RESULT
METRICS_LOGS_TRACES_PROBES_ALERTS_RESULT
SOAK_RESULT
ROLLBACK_PROOF
OPEN_FINDINGS
CAPABILITY_STATE
PRODUCTION_STATE
```

Attach or link workflow runs, artifacts, SBOMs, provenance, signatures, scans and server evidence. Do not include secrets or sensitive customer data.

## 2. Final status vocabulary

Use only:

```text
PASS
WARNING
FAIL
N/A
```

The overall production verdict may be:

```text
PRODUCTION_CERTIFIED_WRITE_DISABLED
PRODUCTION_LIVE_WITH_EXPLICIT_NONBLOCKING_WARNINGS
PRODUCTION_NO_GO
```

`PRODUCTION_CERTIFIED_WRITE_DISABLED` requires every production-critical core gate to be `PASS` or explicitly justified `N/A`, zero unresolved critical/high findings, complete rollback evidence, and all external-effect capabilities disabled.

## 3. Capability activation queue

Create one separate activation work item per capability. No capability may inherit approval from the core deployment.

Required candidate work items:

```text
Codestra SDK / Middleware command delivery
Odoo CRM writes
n8n workflow delivery
bank connection / Plaid
KYB provider
credit provider
lender submission provider
DocuSign send/void
object storage
malware scanning
email provider
SMS provider
payment provider
funding and payouts
tax filing
live dialing
```

Each work item must define:

- owning repository/repositories and exact reviewed SHAs;
- provider/account/environment;
- contract and data classification;
- secret source and least-privilege policy;
- sandbox/staging evidence;
- idempotency and duplicate-effect protection;
- ambiguous-outcome read-back/reconciliation;
- rate/limit/kill switch;
- monitoring and alert thresholds;
- canary population and maximum effect;
- rollback/disable action;
- business, security, compliance and finance owner approvals as applicable;
- production activation UTC and post-activation review.

## 4. Activation order

Use risk-based sequencing. A recommended order is:

1. read-only provider health/capability checks;
2. object storage and malware scanning with synthetic files;
3. internal Middleware/SDK events with no customer communication or financial effect;
4. Odoo/n8n isolated synthetic synchronization;
5. email/SMS sandbox or allowlisted internal recipients;
6. bank/KYB/credit sandbox and limited canary;
7. lender/e-sign controlled canary;
8. payments/funding/payouts only after finance reconciliation and rollback proof;
9. tax filing and live dialing only under their own legal/operational authority.

The actual approved order may differ, but no high-impact capability may activate merely because a lower-risk capability passed.

## 5. Per-capability activation transaction

For each approved capability:

1. verify the current core release is still certified;
2. verify the capability-specific source and configuration lock;
3. verify secret and network scope;
4. verify sandbox/staging tests;
5. verify kill switch and rollback;
6. enable only the single capability or smallest dependency set;
7. run a bounded canary;
8. inspect domain record, audit, idempotency, provider read-back, outbox/inbox and reconciliation evidence;
9. inspect metrics/logs/traces/alerts;
10. either certify, disable/rollback, or place in reconciliation-required state;
11. update the release/capability ledger.

Do not activate multiple consequential providers simultaneously when evidence would become ambiguous.

## 6. Continuous remediation after go-live

A production defect must follow the repository authority cycle:

```text
observe and contain
  -> identify owning repository
  -> create branch and fix
  -> add regression test
  -> protected review and exact-head CI
  -> immutable artifact and updated lock
  -> staging/canary
  -> deploy by digest
  -> verify and close evidence
```

No direct production-only source patch is considered complete. Emergency containment may disable a capability or roll back an immutable release, but the durable fix still belongs in the owning repository.

## 7. Required final issue comment

Post to issue #44:

```text
MONEYBEE_FINAL_STATUS

MISSION_ID=MONEYBEE_CONTINUOUS_REPOSITORY_TO_PRODUCTION_2026_09_02
TARGET_HOST=49.12.145.107
RELEASE_ID=<value>

BACKEND_MAIN_SHA=<value>
FRONTEND_MAIN_SHA=<value>
SDK_SHA=<value>
RUNTIME_AUTHORITY_SHA=<value>
ALEMBIC_HEAD=<value>

REPOSITORY_PHASE_CERTIFIED=<YES|NO>
IMMUTABLE_RELEASE_VERIFIED=<PASS|FAIL>
BACKUP=<PASS|FAIL>
ISOLATED_RESTORE=<PASS|FAIL>
DATABASE_ROLE_SEPARATION=<PASS|FAIL>
MIGRATION_ONE_SHOT=<PASS|FAIL>
PUBLIC_DOMAINS_TLS=<PASS|FAIL>
IDENTITY_PORTAL_ISOLATION=<PASS|FAIL>
API_FRONTENDS=<PASS|FAIL>
INTEGRATION_SYNC=<PASS|FAIL>
OBSERVABILITY_ALERTS=<PASS|FAIL>
CANARY=<PASS|FAIL>
ROLLBACK_PROOF=<PASS|FAIL>
SOURCE_RUNTIME_DRIFT=<PASS|FAIL>

EXTERNAL_EFFECTS_ENABLED=false
PRODUCTION_STATE=LIVE_WITH_EXTERNAL_EFFECTS_DISABLED
OVERALL_VERDICT=<value>

OPEN_WARNINGS=<value>
EVIDENCE_LINKS=<value>
```

Do not report `PASS`, `CERTIFIED`, `LIVE` or `GO` without inspectable evidence linked to the exact source and release.

## Exit gate

Phase 07 is `GO` only when:

```text
FINAL_CERTIFICATION_PACKET_PUBLISHED=YES
PRODUCTION_STATE=LIVE_WITH_EXTERNAL_EFFECTS_DISABLED
CORE_CRITICAL_HIGH_FINDINGS=0
CAPABILITY_ACTIVATION_QUEUE_CREATED=YES
NO_UNAPPROVED_EXTERNAL_EFFECT_ENABLED=YES
ISSUE_44_FINAL_STATUS_POSTED=YES
```

The core mission is then complete. External capability activations remain separate missions until individually certified.
