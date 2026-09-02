# Repository draft audit — 2026-09-02

Baseline: `8a54b265f5296357ed5110e2d497c8d78f19189b` (PR #47 merge into
`development`). This review separates unfinished code from words such as
`DRAFT` and `PARTIAL` that are intentional domain or evidence states.

## Corrected in this audit

| Artifact | Finding | Resolution |
| --- | --- | --- |
| `ops/deploy-staging.sh` | Fail-only deployment placeholder | Replaced by a staging-only, verified-lock, dry-run-first executor. Execution requires a second explicit confirmation; it cannot target production. |
| `app/worker.py` | Docstring said contract delivery was not wired although `run()` invokes it | Corrected the stale documentation; lease/retry behavior remains unchanged. |
| `docs/codex/CONTRACTS_FUNDING_COMMISSION_RENEWAL_SPEC_DRAFT.md` | Implemented design still presented as a current draft | Marked as implemented historical design evidence without erasing decisions. |

## Intentional states — no implementation gap

- `DRAFT` on contracts, offers, and lender submissions is a valid lifecycle
  state.
- JSON Schema's `draft/2020-12` identifies a published schema dialect.
- `PARTIALLY_RECEIVED` and partial payment periods are business concepts.
- Pull-request templates deliberately default overall readiness to `PARTIAL`;
  evidence is required to change it.

## Historical evidence — preserved

Architecture blueprints, prior review packets, and dated evidence files retain
the status observed when they were written. Rewriting these to `PASS` would
destroy audit history. Current readiness is computed by application gates and
current evidence, not by editing historical prose.

## Genuine open gates

The current hardening plan truthfully remains `PARTIAL` for repository-wide PII
expand/backfill/reveal coverage, exhaustive command inventory, full
OpenTelemetry/alert implementation, and exhaustive PostgreSQL concurrency
coverage. These are not draft placeholders and were not relabeled. Operational
backup, PITR, off-host restore, Redis recovery, staging, and production evidence
also require execution outside a repository review.

No production server, database, Redis instance, routing, secret, or provider
capability was changed by this audit.

## Open draft pull requests

Nineteen draft PRs were open during the audit. They must not be bulk-merged:
many form an obsolete, stacked history and several target `main` rather than
the active `development` integration branch.

- Already contained by `development`: #2, #8, #9, #12, #13, #14, #15, and
  #19. These are historical/superseded drafts and can be closed with a link to
  this audit; merging them would add no code.
- Old stacked portal lineage: #3, #4, #5, #6, #7, and #10. Their branches are
  not literal ancestors because later consolidation/rework changed commit
  identity. They require archival comparison, not blind merge.
- Separate current proposals: #21 (n8n handoff), #34 (Keycloak boundary), #36
  (repository profile), #37 (public/API contract), and #46 (Codestra Orbit
  registration). Each must be rebased or retargeted to `development`, reviewed
  for semantic differences from the merged implementation, and pass exact-head
  checks before it can be marked ready.

This branch does not change PR draft state or close historical PRs. That keeps
review history recoverable and avoids treating stale green checks as evidence
for a different current head.
