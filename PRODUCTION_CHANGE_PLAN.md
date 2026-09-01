# MoneyBee Production Change Plan

## Decision

**REPOSITORY CANDIDATE ONLY — do not execute a staging or production deployment from this document.** PR 38 closes the repository-level migration, privilege, compliance, concurrency, retry, and release-contract blockers. Environment-owned backup/restore, PITR, off-host DR, immutable registry digests, and an approved change window remain mandatory before deployment.

## Candidate release

- Source baseline: PR 38 exact head; record the final SHA after required checks and reviews pass.
- Current deployed source: not re-verified by this repository-only change.
- Current production Alembic revision: must be captured in the approved pre-change baseline.
- Candidate Alembic head: `20260901_0024`.
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
| Existing chain through `0022` | SHORT LOCK | Rehearsal evidence exists, but lock behavior must be measured again against the current approved restore. |
| `20260901_0023` bank credential reference | MAINTENANCE WINDOW REQUIRED | Fails closed on unresolved legacy credential rows and requires an approved credential-reference transition. Downgrade refuses to strand external references. |
| `20260901_0024` provider retry and notice uniqueness | SHORT LOCK | Adds nullable retry columns and a uniqueness constraint after rejecting duplicate legacy notice evidence. Re-measure on current restored data. |

## Rollback

- Application rollback is permitted only to an immutable prior digest that remains compatible with the post-migration schema.
- Database rollback uses PITR to the recorded pre-change recovery point or a reviewed Alembic downgrade where proven safe. Never overwrite production without incident authorization.
- Migration `0023` preserves data by refusing unsafe upgrade/downgrade paths; use a reviewed forward fix if its protection triggers.
- If readiness, runtime grants, or financial invariant tests fail, stop traffic to the candidate release and return to the compatible prior image; do not edit financial rows manually.

## Required approval evidence

- Exact-head GitHub checks and fresh code/human review pass.
- Current production-derived rehearsal through `20260901_0024` passes.
- Verified off-host backup retrieval and PITR recovery point.
- Immutable image provenance/SBOM/security gate.
- Approved external object storage and malware scanner.
- Named change owner and explicit production execution approval.
