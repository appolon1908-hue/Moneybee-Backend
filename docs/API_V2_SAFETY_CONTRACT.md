# MoneyBee API V2 Safety Contract

The only runtime contract between the frontend and backend repositories is the typed REST/OpenAPI API at `https://api.moneybeeloan.com/api/v2`.

Creating a table, endpoint, adapter, worker, or screen never activates a live production capability.

## Mandatory decision chain

A production-sensitive action may execute only when all of these are true:

1. The endpoint exists and the request is valid.
2. The authenticated actor has permission and record-level access.
3. The capability flag is enabled for the active environment.
4. A required provider connection exists.
5. The provider is `READY`.
6. Required credentials and configuration are available.
7. The application state machine permits the transition.
8. The command is idempotent, audited, and transactionally recorded.

Backend enforcement is authoritative. Frontend feature hiding is not security.

## Fail-closed capabilities

Production seeds these disabled:

- `crm.write`
- `bank.live_connection`
- `kyb.live_verification`
- `credit.live_pull`
- `lenders.live_submission`
- `esign.live_send`
- `communications.live_email`
- `communications.live_sms`
- `funding.live_confirmation`
- `matching.auto_submit`
- `adverse_action.live_delivery`

High-risk activation must be controlled by an authorized release process and configuration, not by an unrestricted UI toggle.

## Provider readiness

Provider states are `NOT_CONFIGURED`, `CONFIGURED`, `VERIFYING`, `READY`, `DEGRADED`, and `DISABLED`. An enabled capability whose named provider is not `READY` remains unavailable.

## Implemented foundation

- `capability_flags` and `provider_connections` models
- Alembic migration with production-disabled seeds
- effective capability evaluation
- `GET /api/v2/me/capabilities`
- `GET /api/v2/admin/capabilities`
- `GET /api/v2/admin/provider-connections`
- reusable `require_capability` service
- canonical v2 OpenAPI with hidden v1 compatibility routes

## Still required

Record-level borrower/lender organization authorization, persisted idempotency middleware, signed webhook verification, real provider health checks, credential-presence validation, state-specific provider commands, immutable activation audit, and controlled administrative activation are P0 gaps.
