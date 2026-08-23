# Step 1B — Backend Local Identity and Tenancy

Work package:

auth/local-identity-tenancy

Status:

FIRST BACKEND IMPLEMENTATION PR

## Objective

Convert valid Keycloak identity into authoritative local MoneyBee identity.

Current JWT claims must not remain the sole application authorization model.

## Identity Key

Use:

issuer + subject

Never email.

## Add Tables

users

external_identities

organizations

organization_memberships

roles

permissions

role_permissions

user_role_bindings

## external_identities

Fields:

id
user_id
issuer
subject
created_at
last_seen_at

Constraint:

UNIQUE(issuer, subject)

## users

Fields:

id
email
display_name
active
created_at
updated_at

## organizations

At minimum:

BORROWER
LENDER
MONEYBEE
AFFILIATE

## organization_memberships

Fields:

organization_id
user_id
membership_type
active
created_at

## Principal

Implement:

Principal
- user_id
- issuer
- subject
- organization_ids
- active_organization_id
- roles
- permissions
- borrower_id
- lender_id
- is_active

## Resolution Flow

JWT validation

→ issuer + subject

→ external identity

→ active local user

→ active membership

→ roles / permissions

→ Principal

## JWT Requirements

Explicitly require:

iss
sub
aud
exp
iat
nbf

Validate:

signature
issuer
audience
algorithm
kid
JWKS
expiration
not-before
issued-at

## Production Rejections

Unknown identity:

401 IDENTITY_NOT_BOUND

Disabled user:

403 USER_DISABLED

Inactive membership:

403 MEMBERSHIP_INACTIVE

Wrong tenant:

403 TENANT_ACCESS_DENIED

Wrong resource:

403 RESOURCE_ACCESS_DENIED

## Remove Broad Static Authority

Do not rely permanently on:

MONEYBEE_ADMIN = *

Create database-backed permissions.

## Borrower Authorization

Borrower access requires:

authenticated Principal
+
active borrower membership
+
resource ownership / organization relationship

## Lender Authorization

Lender access requires:

authenticated Principal
+
active lender membership
+
submission lender ownership

## Migration

Additive Alembic migration.

Do not remove old claims-based compatibility until new identity binding passes staging.

Do not use create_all.

## Required Tests

wrong issuer rejected

wrong audience rejected

expired JWT rejected

missing subject rejected

missing expiration rejected

unknown identity rejected

disabled local user rejected

inactive membership rejected

Borrower A cannot access Borrower B

Lender A cannot access Lender B

borrower cannot use admin endpoint

staff without permission rejected

Tests involving authorization persistence must run against PostgreSQL.

## OpenAPI

Document stable errors:

AUTHENTICATION_REQUIRED

IDENTITY_NOT_BOUND

USER_DISABLED

MEMBERSHIP_INACTIVE

TENANT_ACCESS_DENIED

RESOURCE_ACCESS_DENIED

## Rollback

Code rollback:

restore prior resolver temporarily

Database:

new identity tables are additive and should normally remain

Production:

prefer forward-fix over dropping identity data

## PR Evidence

WORK_PACKAGE=auth/local-identity-tenancy

SOURCE_SHA=

MIGRATION_HEAD_BEFORE=

MIGRATION_HEAD_AFTER=

JWT_VALIDATION=

LOCAL_IDENTITY=

TENANCY=

BORROWER_ISOLATION=

LENDER_ISOLATION=

POSTGRES_TESTS=

SECURITY_TESTS=

OPENAPI=

ROLLBACK_DOCUMENTED=

LIVE_CAPABILITIES_ENABLED=NONE

OVERALL_SYSTEM_STATUS=PARTIAL

