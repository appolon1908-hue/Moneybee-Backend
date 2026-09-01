# MoneyBee Production Change Plan

## Decision

**BLOCKED — do not execute the production migration or application deployment.** The production-derived rehearsal proved the restored database can advance from Alembic `20260827_0016` to `20260901_0022`, but the metadata comparison still detects substantive model/schema drift. Off-host DR, PITR, production document quarantine/storage, and a post-change recovery rehearsal are also absent.

## Candidate release

- Source baseline: `ff3a688b705450f9e2f33a88ad08e16b0c9f6143` plus the uncommitted reviewed changes in this working tree.
- Current deployed source: `07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3`.
- Current production Alembic revision: `20260827_0016`.
- Candidate Alembic head: `20260901_0022`.
- Production images must not be updated until CI produces immutable digest references, an SBOM, and security results.

## Planned sequence after blockers close and owner approves

1. Verify a fresh encrypted backup, successful retrieval from off-host storage, and working WAL archiving.
2. Recreate the rehearsal from that backup and apply the reviewed compatibility migration using `moneybee_migrator`.
3. Run the full test suite, PostgreSQL-backed concurrency/idempotency tests, schema comparison, least-privilege smoke tests, and application recovery test.
4. Record the release commit and immutable image digests.
5. Put unsafe external integrations into blocked/sandbox mode; take the approved maintenance window if the compatibility migration requires it.
6. Apply migrations exactly once with `moneybee_migrator`; run APIs/workers with `moneybee_runtime`.
7. Verify Alembic head, indexes, constraints, privileges, readiness, authentication, tenant isolation, rate limiting, documents, outbox/inbox, and logs.
8. Create a new backup and complete another isolated restore of the deployed schema/release.

## Migration safety classification

| Migration | Classification | Reason |
|---|---|---|
| `0016 → 0022` existing chain | SHORT LOCK | Rehearsal completed in 1.633 seconds on the current small restored database, but production lock behavior must be rechecked immediately before change. |
| Required model/schema compatibility migration | MAINTENANCE WINDOW REQUIRED | Not yet authored; it must reconcile bank credential storage and constraint/index identity without losing access to provider credentials. |

## Rollback

- Application rollback is permitted only to an immutable prior digest that remains compatible with the post-migration schema.
- Database rollback uses PITR to the recorded pre-change recovery point or a reviewed Alembic downgrade where proven safe. Never overwrite production without incident authorization.
- Preserve the old credential column until the new reference path is populated and read compatibility is proven.
- If readiness, runtime grants, or financial invariant tests fail, stop traffic to the candidate release and return to the compatible prior image; do not edit financial rows manually.

## Required approval evidence

- Reviewed compatibility migration and production-derived rehearsal pass.
- Verified off-host backup retrieval and PITR recovery point.
- Immutable image provenance/SBOM/security gate.
- Approved external object storage and malware scanner.
- Named change owner and explicit production execution approval.
