# MoneyBee release-readiness packet

Mission: `MB-CODE-AND-RELEASE-READINESS-20260827`

This packet is review-only. It grants no authority to contact a host, publish a
release, run a migration outside CI, or deploy an image.

## Reviewed integration inputs

- Backend start: `fb2866b033811bcb1c5e2522dc23bd350866164b`
- Backend finance source: `07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3`
- Frontend start: `b7b0abb17a3325ba04941b60d548897a9bf7e93d`
- Frontend finance source: `033e2190de4b9cf78f73c6d1a81f8668c5efef83`

The draft integration PR descriptions are the authoritative record of the
final exact heads and exact-head workflow results.

## Required protected checks

Backend protection must require the repository's verify,
PostgreSQL identity/tenancy, and API/worker/migrate container jobs. Frontend
protection must require validation plus all four portal container jobs. A
fresh independent review is required after the final head changes. Neither PR
may auto-merge.

## Digest-only release lock template

Populate only from a separately approved image publication workflow:

```text
BACKEND_SHA=<40-hex>
FRONTEND_SHA=<40-hex>
MIGRATION_HEAD=20260827_0018

API_IMAGE=registry/repository@sha256:<64-hex>
WORKER_IMAGE=registry/repository@sha256:<64-hex>
MIGRATE_IMAGE=registry/repository@sha256:<64-hex>
MARKETING_IMAGE=registry/repository@sha256:<64-hex>
BORROWER_IMAGE=registry/repository@sha256:<64-hex>
LENDER_IMAGE=registry/repository@sha256:<64-hex>
ADMIN_IMAGE=registry/repository@sha256:<64-hex>
```

Mutable tags such as `latest` are prohibited in an approved release lock.

## Capability freeze

```text
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

The future executor must fail closed if any value differs.

## Migration, backup, restore, and rollback review

Before any future staging mutation, an authorized operator must record the
database identity, current Alembic revision, backup command, encrypted backup
artifact checksum, and a successful restore drill into an isolated database.
The migration sequence is backup, verify restore evidence, run the dedicated
digest-locked migrate image once, verify `20260827_0018 (head)`, then start the
application images. A migration failure stops the rollout.

Rollback must restore the previous digest lock and application services without
deleting PostgreSQL or Redis volumes. Database rollback uses a reviewed forward
fix or the verified pre-change backup; `alembic downgrade base` is prohibited on
a staging or production database.

## Runtime-path questions for later authorization

- What exact host and maintenance window are approved?
- Which operator or protected executor is authorized?
- What are the reviewed Compose, environment, secret, and proxy mount paths?
- What current database revision and backup/restore evidence were verified?
- Which immutable registry digests and signatures are approved?
- Which health checks and rollback thresholds control cutover?

These questions are documentation only. This mission does not authorize a
read-only preflight or any deployment action.

## Required later authorization

A later approval must identify the target host, maintenance window, protected
merged SHAs, immutable image digests, reviewed runtime paths, backup and tested
restore evidence, migration/rollback plan, authorized executor, and exact
capabilities. It must include the literal authorization statement required by
the deployment mission. Until then:

```text
READ_ONLY_PREFLIGHT_RUN=NOT_AUTHORIZED
DEPLOYMENT_RUN=NOT_AUTHORIZED
SERVER_UPDATED=NO
STAGING_DEPLOYED=NO
PRODUCTION_CHANGED=NO
GO_NO_GO=NO_GO
```
