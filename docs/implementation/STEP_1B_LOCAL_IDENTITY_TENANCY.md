# Step 1B — Local Identity, Tenancy and RBAC

Status: PLANNED / BLOCKED_ON_STEP0_MERGE
Branch (after Step-0 approval/merge): `auth/local-identity-tenancy`

## Hard gate

Do not create or implement this branch until the Step-0 backend PR is approved and merged to `main`.

Step 2 and all financial workflows remain blocked until this PR and frontend Step 1A are merged and integration-tested.

## Identity authority

A valid Keycloak token is not sufficient by itself. MoneyBee must translate the token into an authoritative local `Principal`.

Durable identity key:

`issuer + subject`

Email is profile data only and must never be used as the durable identity key.

## OIDC verification

Validate all of the following:

- signature
- allowed algorithm
- issuer
- audience (`moneybee-api`)
- subject
- expiration
- issued-at
- not-before
- key ID
- approved authorized party (`azp`)
- JWKS caching and key rotation

Use discovery/JWKS from the configured issuer. Production must retain the repository-approved canonical issuer configuration.

## Local identity schema

Add migration `0002_identity_tenancy_rbac` using the actual Step-0 revision as `down_revision`.

Create database-backed identity/RBAC tables for:

- `users`
- `external_identities`
- `organizations`
- `organization_memberships`
- `roles`
- `permissions`
- `role_permissions`
- `membership_roles`

Required organization types:

- `BORROWER`
- `LENDER`
- `MONEYBEE`
- `AFFILIATE`

Enforce uniqueness for `external_identities(issuer, subject)` and membership uniqueness per organization/user.

## Principal

The resolved principal must include at least:

- local user ID
- issuer
- subject
- active organization ID
- organization type
- roles
- permissions
- active status context

No `MONEYBEE_ADMIN = *` shortcut is permitted. Authorization is database-backed.

## API surface

Implement:

- `GET /api/v2/auth/me`
- `GET /api/v2/auth/context`

The organization selector header is:

`X-MoneyBee-Organization: <organization-id>`

The header is a requested context, not authorization. MoneyBee must validate membership, organization status, roles, permissions, and later record ownership/tenant scope independently.

Do not add arbitrary token self-registration such as `POST /auth/register-from-token`. Provisioning remains explicit invite/admin/onboarding behavior.

## Required failures

- `401 AUTHENTICATION_REQUIRED`
- `401 INVALID_ACCESS_TOKEN`
- `401 IDENTITY_NOT_BOUND`
- `403 USER_DISABLED`
- `403 MEMBERSHIP_INACTIVE`
- `403 TENANT_ACCESS_DENIED`
- `403 RESOURCE_ACCESS_DENIED`

Errors must not leak SQL, user, membership, or internal authorization details.

## Record-level authorization

Permission checks are necessary but insufficient. Every tenant-owned repository query must also constrain the resource to the principal's active organization/tenant.

## Initial permission catalog

Seed explicit permissions rather than wildcard roles, including:

- `application.read`, `application.manage`
- `bank_connection.read`, `bank_connection.manage`
- `verification.read`, `verification.manage`
- `credit.read`, `credit.request`
- `lender_submission.read`, `lender_submission.manage`
- `condition.read`, `condition.submit`, `condition.decide`
- `offer.read`, `offer.accept`
- `contract.read`, `contract.manage`
- `funding.read`, `funding.approve`, `funding.send`, `funding.confirm`, `funding.reconcile`
- `commission.read`, `commission.adjust`
- `pii.view_masked`, `pii.reveal`
- `integration.read`, `integration.retry`
- `admin.users.read`, `admin.users.manage`
- `admin.roles.read`, `admin.roles.manage`
- `admin.capabilities.read`, `admin.capabilities.manage`

Presence of a permission never overrides capability activation.

## Mandatory tests

- valid token + bound user -> allowed
- valid token + unbound identity -> `401 IDENTITY_NOT_BOUND`
- disabled user -> `403 USER_DISABLED`
- inactive membership -> `403 MEMBERSHIP_INACTIVE`
- unknown organization -> `403 TENANT_ACCESS_DENIED`
- Org A user requesting Org B -> denied
- granted permission -> allowed
- missing permission -> `403 RESOURCE_ACCESS_DENIED`
- wrong issuer -> 401
- wrong audience -> 401
- expired token -> 401
- wrong `azp` -> 401
- unsigned token -> 401
- wrong algorithm -> 401
- rotated JWKS key -> refresh JWKS and succeed
- email change does not change identity resolution
- PostgreSQL migration/rollback proof
- cross-borrower, cross-lender and cross-affiliate isolation proof

## Acceptance evidence

```text
BRANCH=auth/local-identity-tenancy
OIDC_SIGNATURE=PASS
OIDC_ISSUER=PASS
OIDC_AUDIENCE=PASS
OIDC_AZP=PASS
IDENTITY_KEY=issuer+subject
LOCAL_IDENTITY=PASS
TENANCY=PASS
RBAC=PASS
CROSS_BORROWER=PASS
CROSS_LENDER=PASS
CROSS_AFFILIATE=PASS
DISABLED_USER=PASS
INACTIVE_MEMBERSHIP=PASS
POSTGRES_TESTS=PASS
MIGRATION_TESTS=PASS
LIVE_CAPABILITIES_ENABLED=NONE
PRODUCTION_DEPLOYED=NO
```

## Completion gate

Step 2 (`commands/command-context`) may begin only after Step 1A and Step 1B are both merged and integration evidence shows:

- `AUTH_E2E=PASS`
- `LOCAL_IDENTITY=PASS`
- `TENANT_ISOLATION=PASS`
- `AUTHORIZATION=PASS`

Do not jump from identity directly to Step 9. Financial capabilities remain disabled.

## Current prerequisite state

```text
STEP0_PR_STATE=DRAFT
STEP0_MERGED=NO
STEP1B_BRANCH_CREATED=NO
STEP1B_IMPLEMENTED=NO
LIVE_CAPABILITIES_ENABLED=NONE
PRODUCTION_DEPLOYED=NO
```