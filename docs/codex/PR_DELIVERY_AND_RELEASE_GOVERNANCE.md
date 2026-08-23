# PR Delivery and Release Governance

Every implementation step in this specification MUST be delivered as a separate, independently reviewable pull request.

No step may be bundled into a large multi-phase PR unless explicitly approved.

Each PR must contain all applicable parts of the following delivery contract.

## Required PR Contents

1. Implementation
2. Additive database migration
3. Rollback / downgrade plan
4. Unit tests
5. PostgreSQL integration tests where applicable
6. Security / authorization tests
7. Concurrency tests where applicable
8. OpenAPI contract changes
9. Operational documentation
10. Deployment / rollback notes
11. Readiness evidence
12. Known limitations and blockers

A PR is not considered complete because code compiles or CI is green.

CI-green means only that the PR passed its current automated checks.

It does NOT mean:

- approved for merge
- approved for deployment
- production-ready
- provider-certified
- capability-enabled
- safe for live lending
- safe for live funding

---

## Capability Freeze

During all implementation PRs, the following live capabilities MUST remain disabled:

```text
credit.live_pull = false
lenders.live_submission = false
esign.live_send = false
funding.live_confirmation = false
payments = false
payouts = false
```

No implementation PR may automatically enable one of these capabilities.

No migration may seed them enabled.

No deployment script may enable them.

No UI control may silently enable them.

No readiness check may infer them enabled because credentials exist.

Capability activation is a separate production-governance action after launch certification.

---

## Merge Policy

Codex MUST NOT automatically merge any PR.

Each PR must be left in a reviewable state.

Required workflow:

```text
implementation
→ tests
→ CI
→ review evidence
→ human review
→ explicit merge approval
```

Codex may open or update a draft PR.

Codex must not:

- auto-merge
- force-push over reviewed work
- bypass required checks
- bypass branch protection
- deploy because CI passed

---

## Deployment Policy

No individual PR should automatically deploy to production.

A PR may deploy to staging only if the repository's approved CI/CD process explicitly supports staging deployment for that work package.

Production deployment is permitted only after the complete launch gate has passed.

---

## Readiness Policy

The MoneyBee system readiness endpoint/report MUST remain:

```text
FINAL_STATUS = PARTIAL
```

or:

```text
FINAL_STATUS = BLOCKED
```

until:

1. All implementation steps through Step 12 are complete.
2. Every mandatory launch gate has passed.
3. Production evidence exists for every required gate.
4. Dangerous capabilities have separate explicit approval.

No intermediate PR may set:

```text
FINAL_STATUS = READY
```

even if that PR itself is fully implemented and CI-green.

---

## Readiness Evidence Per PR

Each PR must provide machine-readable readiness evidence such as:

```json
{
  "work_package": "integration/durable-inbox",
  "status": "PASS",
  "source_sha": "...",
  "migration_head": "...",
  "unit_tests": "PASS",
  "postgres_tests": "PASS",
  "security_tests": "PASS",
  "concurrency_tests": "NOT_APPLICABLE",
  "openapi_status": "PASS",
  "rollback_documented": true,
  "staging_verified": false,
  "production_enabled": false,
  "blockers": []
}
```

This PR-level status does NOT change overall system readiness to READY.

---

## Migration Policy

Every schema-changing PR must use additive migration practices.

Preferred:

```text
expand
→ compatible application deployment
→ backfill
→ validate
→ contract
```

Each migration PR must include:

- migration file
- expected current migration head
- expected new migration head
- upgrade test
- downgrade / rollback strategy
- PostgreSQL migration test
- compatibility statement

Do not use `Base.metadata.create_all` as a production migration.

Do not manually modify the production database.

---

## Rollback Requirement

Every PR must describe its rollback behavior.

At minimum document:

- code rollback
- schema compatibility
- configuration rollback
- worker rollback
- provider impact
- data backfill impact
- whether downgrade migration is safe
- whether forward-fix is preferred

If a migration cannot safely be reversed, state this explicitly and provide a forward-fix strategy.

---

## OpenAPI Requirement

Any API-changing PR must:

1. Update request/response schemas.
2. Regenerate OpenAPI.
3. Add or update endpoint tests.
4. Validate compatibility with existing clients.
5. Document new error codes.
6. Document Idempotency-Key requirements.
7. Document If-Match requirements.
8. Document permissions.
9. Document ownership/tenant rules.
10. Document emitted events.

OpenAPI contract drift must fail CI.

---

## Security Requirement

Any PR involving authentication, authorization, PII, tenancy, lenders, contracts, funding, webhooks, documents, or operations MUST contain negative security tests.

Examples:

- wrong tenant rejected
- wrong borrower rejected
- wrong lender rejected
- missing permission rejected
- disabled user rejected
- disabled capability rejected
- stale version rejected
- duplicate action produces one result
- duplicate webhook produces one effect
- restricted PII not exposed

---

## PostgreSQL Test Requirement

Any PR relying on:

- transactions
- row locks
- concurrency
- unique constraints
- `SKIP LOCKED`
- JSONB
- PostgreSQL-specific indexes
- partial indexes
- advisory locks
- isolation semantics

must include tests against PostgreSQL.

SQLite-only tests are not sufficient.

---

## Operational Documentation Requirement

Every PR must add or update operational documentation covering:

- purpose
- normal operation
- health signal
- metrics
- alerts
- failure modes
- retry behavior
- manual recovery
- rollback
- ownership
- permissions required for recovery actions

Operators must not need direct database editing for normal recovery.

---

## Final Rule

A PR being CI-green is evidence that the PR passed its checks.

It is not authority to:

- merge
- deploy
- activate capabilities
- change readiness to READY
- allow real funding

Only the complete production launch process can do that.
