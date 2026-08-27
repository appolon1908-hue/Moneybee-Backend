# MoneyBee Codex Start Here

## Current mission

Execute:

`docs/codex/CODEX_MONEYBEE_STAGING_DEPLOYMENT_MISSION.md`

Mission ID:

```text
MB-STAGING-SERVER-UPDATE-20260827
```

The current objective is to integrate the reviewed authentication, portal-contract, finance-ledger, and secure staging-scaffold work; create protected staging release SHAs; prove the candidate host and runtime paths; publish immutable digest-pinned images; and update the approved **staging** server through the protected deployment boundary.

## Integration branches

```text
Backend repository:
integration/staging-moneybee-20260827
starting SHA: fb2866b033811bcb1c5e2522dc23bd350866164b
finance head to integrate: 07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3

Frontend repository:
integration/staging-moneybee-20260827
starting SHA: b7b0abb17a3325ba04941b60d548897a9bf7e93d
finance head to integrate: 033e2190de4b9cf78f73c6d1a81f8668c5efef83
```

Frontend PR #18 is a separate design-system PR and is not part of this server-update mission.

## Execution order

1. Verify every recorded source SHA and exact-head workflow.
2. Integrate the finance heads into the dedicated integration branches without unrelated feature work.
3. Run full backend and frontend validation at the resulting exact heads.
4. Create and protect `release/staging` in both repositories.
5. Merge only through reviewed protected pull requests.
6. Build, sign, scan, attest, and publish images from the protected merged SHAs.
7. Run the read-only runtime-path preflight for candidate host `49.12.145.107`.
8. Stop if host identity, workload ownership, paths, backup storage, secrets, or branch protection are unresolved.
9. Generate and review the release/runtime locks and readiness packet.
10. Use a separately reviewed protected staging deployment executor to apply the immutable digest tuple.
11. Verify health, release identity, tenant isolation, separate portal tokens, finance flows, restart behavior, and rollback.
12. Return the exact evidence record required by the mission.

## Non-negotiable safety boundary

```text
PRODUCTION_AUTHORIZATION=NOT_GRANTED
PRODUCTION_CHANGED=NO
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

The existing `staging-deployment-readiness-packet` workflow does not update a remote server. Never report deployment success from that workflow alone.

Do not auto-merge. Do not force-push. Do not deploy feature branches. Do not store credentials in Git or artifacts. Do not weaken host, identity, tenant, migration, image, backup, or rollback gates.
