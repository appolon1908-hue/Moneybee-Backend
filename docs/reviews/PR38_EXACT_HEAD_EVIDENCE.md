# PR 38 exact-head evidence

This document is the repository evidence record for PR 38. It does not certify
or deploy a live environment. Staging and production remain untouched and all
external delivery/provider writes remain disabled by default.

## Scope and implementation

- Migration `20260901_0023` now discovers columns through SQLAlchemy inspection
  and uses Alembic batch operations on SQLite. Its upgrade still refuses legacy
  plaintext credential rows and its downgrade still refuses to strand external
  credential references.
- Migration `20260901_0022a` provides an explicit compatibility boundary for
  populated legacy credentials. The reference-only staging tool verifies a
  complete `secret://` mapping before `0023` may proceed. Its downgrade
  preserves the canonical column introduced at revision `0009` and removes the
  staged column only from the deployed legacy ciphertext shape.
- Migration `20260901_0024` adds durable provider retry/lease state and prevents
  duplicate adverse-action notices for one underwriting review.
- Migration `20260901_0025` fail-closes on duplicate contracts, enforces one
  contract per offer, and adds durable inbox callback retry scheduling.
- `moneybee_migrator` owns the application schema and existing application
  objects after an idempotent administrator-run transfer. `moneybee_runtime`
  has DML/sequence/function access only and cannot perform DDL, truncate, grant,
  create roles/databases, replicate, or bypass RLS.
- Admin and lender decline paths share one idempotent adverse-action service.
  Every offer-creation route shares one offer/disclosure transaction service.
- Disclosure repayment calculations use Decimal, explicit HALF_UP cent
  rounding, and documented monthly/weekly/biweekly/semimonthly/daily
  conventions. Irregular schedules require an authoritative total.
- PostgreSQL row locks serialize commission receipts and split-capacity checks.
  Adjustments use the same parent lock, cannot invalidate committed receipts or
  splits, and recompute status atomically. Receipt overpayment is rejected.
- Document and e-sign provider jobs persist attempts, bounded exponential
  backoff with jitter, retry time, leases, safe errors, and terminal state.
- Compose files, locks, renderer, preflight validation, and CI use one canonical
  environment contract with separate migrator/runtime identities and immutable
  image references. No target-server source build is permitted.
- Release images do not trust proxy headers in Uvicorn; the application-owned
  proxy policy remains authoritative.
- A secret-backed one-shot Compose bootstrap service provisions/transfers roles
  before Alembic; API and worker never receive the administrator identity.
- DocuSign envelope creates carry the stable contract UUID as the provider
  transaction ID, closing the accepted-response-lost duplicate window. Connect
  callback event names are normalized and envelope-summary status is preferred.
- Offer acceptance locks and verifies the generated disclosure and refuses to
  create funding until authenticated acknowledgment evidence exists. Borrower
  read/acknowledgment routes enforce application ownership and share the same
  acknowledgment service used by the admin route.
- Funding, contract, condition-completion, renewal, and commission transitions
  use PostgreSQL aggregate locks. Provider callbacks retry if they arrive before
  envelope persistence, and sent-envelope voids are confirmed upstream first.

## Migration contract

- Before: `20260901_0023`
- After: `20260901_0025`
- SQLite: empty upgrade, downgrade to base, and re-upgrade pass.
- PostgreSQL: empty-to-head, historical-to-head, forward-fix, fail-closed legacy
  credential, and protected downgrade paths pass.
- Downgrade limitation: `0023` intentionally aborts if an external credential
  reference would be stranded. `0024` intentionally aborts if provider retry
  evidence would be discarded. Forward-fix is the operational default.

## API, authorization, tenancy, and compatibility

- Canonical OpenAPI remains `/api/v2`; compatibility routing under `/api/v1`
  is derived from the same route implementations and remains excluded from the
  canonical document.
- No duplicate V1 business logic was introduced.
- Admin writes use write-authorized resource loading; lender resources retain
  tenant/application ownership enforcement.
- Replay keys preserve one result for adverse notices, receipts, and splits.
- Existing transactional outbox/inbox behavior remains enabled; live delivery
  remains fail-closed.

## Reproducible gates

Run from repository root:

```text
git diff --check
python -m ruff check app tests migrations scripts ops
python -m compileall -q app tests migrations scripts ops
python scripts/check_no_private_keys.py
python scripts/check_identity_email_readiness.py
python -m pytest -q
python scripts/smoke_api.py
python scripts/verify_openapi_contract.py
python scripts/generate_endpoint_catalog.py --check
python ops/verify-compose-contract.py
```

Observed on implementation head `c03f049e84472b89c5847794128a9551a4fefc14`:

- SQLite/application tests: 247 passed, 10 skipped.
- Clean PostgreSQL/runtime tests: 258 passed.
- API smoke: 57 passed, 4 intentionally unavailable surfaces skipped.
- OpenAPI: 159 canonical paths and 39 reviewed additions.
- Identity/email repository readiness: 20 passed, 21 operator-only checks
  skipped, 0 failed.
- Compose contract: 3 manifests and 28 variables synchronized.
- Private-key scan: no tracked PEM/OpenSSH/PGP private-key blocks.
- API, worker, and migrate release targets built and ran as `moneybee`.
- Trivy: 0 fixable HIGH/CRITICAL findings per release image.
- CycloneDX SBOM generated per release image.

The authoritative final results are the required GitHub Actions checks attached
to the exact PR head; local image IDs are disposable evidence, not deployable
release provenance.

## Operations, rollback, and recovery prerequisites

- Liveness: `/health/live`; readiness: `/health/ready` verifies database,
  migration head, and required Redis connectivity.
- Operational exceptions expose terminal provider retry failures; provider
  attempt/next-attempt fields support retry monitoring and alerting.
- Code rollback requires the prior immutable image digests. Schema rollback is
  allowed only where the migration's data-preservation checks pass; otherwise
  deploy a forward fix.
- Before staging: render an environment from approved external secret paths,
  create and verify a backup, record restore evidence, pin all release digests,
  run the migration image as `moneybee_migrator`, then switch API/worker to
  `moneybee_runtime` and execute the smoke/readiness gates.
- No backup, restore, RPO, or RTO claim is made by repository CI.

## Governance and remaining boundary

`PR_READINESS_STATUS = PASS` is valid only after every required check passes on
the same exact head and fresh code/human review has completed.

`OVERALL_SYSTEM_STATUS = PARTIAL`

`LIVE_CAPABILITIES_ENABLED = NONE`

Repository completion does not authorize merge or deployment. A fresh human
review must cover migrations, finance/concurrency, compliance,
authentication/tenancy, and deployment manifests. Staging still requires
operator-owned immutable release records, external secrets, backup/restore
evidence, and an approved change window.
