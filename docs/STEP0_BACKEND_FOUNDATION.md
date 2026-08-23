# Step 0A — Backend foundation

Status: PARTIAL / NON-PRODUCTION.

This branch establishes the runtime, database migration framework, Redis connectivity, provider-neutral adapter contract, health/version/readiness API and CI foundation. It does not implement lender, credit, e-sign, funding, payment or payout provider behavior.

## Hard safety gates

The following remain false through implementation unless a later independently approved launch gate activates them:

- `credit.live_pull`
- `lenders.live_submission`
- `esign.live_send`
- `funding.live_confirmation`
- `payments`
- `payouts`

## Money representation

Authoritative business-money columns introduced by later domain migrations must use PostgreSQL `NUMERIC(18,2)` as required by the approved blueprint.

## Delivery

Do not deploy this branch. Merge only after review and green CI. Production receives immutable artifacts only after staging, recovery, security, approval and canary gates.
