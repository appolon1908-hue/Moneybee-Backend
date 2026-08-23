# Local Identity and Tenancy Operations

## Purpose

This work package binds a validated Keycloak identity to an authoritative local MoneyBee user,
organization membership, role, and permission set. Keycloak token roles are compatibility-only
outside staging and production; production authorization is database-backed.

## Normal operation

1. Validate the bearer token signature, `kid`, RS256 algorithm, issuer, audience, and required
   `iss`, `sub`, `aud`, `exp`, `iat`, and `nbf` claims.
2. Resolve `external_identities` by immutable `(issuer, subject)`.
3. Reject disabled users and inactive users, organizations, memberships, roles, or bindings.
4. Select the sole active organization, or use `X-Organization-ID` when multiple memberships
   exist.
5. Build `Principal` from local roles and permissions and enforce resource ownership.

Identity records are provisioned through an approved administrative workflow. This PR does not
auto-provision users or grant privileges.

## Configuration

- `OIDC_ISSUER=https://auth.codestra.co/realms/codestra`
- `OIDC_AUDIENCE=moneybee-api`
- `OIDC_JWKS_URL=https://auth.codestra.co/realms/codestra/protocol/openid-connect/certs`
- `OIDC_ALGORITHMS_CSV=RS256`
- `LOCAL_IDENTITY_ENFORCEMENT=true` in staging and production
- `LOCAL_AUTH_BYPASS=false` in staging and production

## Health signals and metrics

The API readiness report must remain `PARTIAL` or `BLOCKED`. Operators should track counters by
stable error code: `IDENTITY_NOT_BOUND`, `USER_DISABLED`, `MEMBERSHIP_INACTIVE`,
`TENANT_ACCESS_DENIED`, `RESOURCE_ACCESS_DENIED`, and `IDENTITY_PROVIDER_UNAVAILABLE`.

Alert when JWKS retrieval failures persist for five minutes, invalid-token rates depart materially
from baseline, or tenant/resource denials spike for one client. Step 11 will add the production
OpenTelemetry metric and alert implementation; until then these are required log-derived signals.

## Failure modes and recovery

| Failure | Signal | Recovery |
| --- | --- | --- |
| Keycloak/JWKS unavailable | 503 `IDENTITY_PROVIDER_UNAVAILABLE` | Verify DNS/TLS and Keycloak health; do not bypass authentication. |
| Identity not bound | 401 `IDENTITY_NOT_BOUND` | Use the approved identity administration workflow to link `(issuer, subject)`. |
| User disabled | 403 `USER_DISABLED` | Confirm employment/customer status; an authorized identity administrator may reactivate. |
| Membership inactive | 403 `MEMBERSHIP_INACTIVE` | Confirm organization relationship before reactivation. |
| Wrong tenant | 403 `TENANT_ACCESS_DENIED` | Correct `X-Organization-ID`; never edit resources into another tenant. |
| Wrong resource | 403 `RESOURCE_ACCESS_DENIED` | Verify ownership and investigate possible enumeration or client defect. |

Authentication and authorization requests are not retried by the API. Clients may retry a 503
after bounded backoff, but must not retry 401/403 without correcting authentication or access.
Normal recovery never requires direct production database editing.

## Migration and rollback

- Expected head before: `20260823_0011`
- Expected head after: `20260823_0012`
- Expansion: eight identity/RBAC tables and nullable `applications.borrower_organization_id`
- Backfill: not performed automatically; existing `borrower_subject` remains compatibility data
- Compatibility: old application rows remain readable; claims fallback is restricted to local,
  test, and dev when `LOCAL_IDENTITY_ENFORCEMENT=false`

Code rollback may restore the prior resolver temporarily outside production. New identity tables
should normally remain because they are additive and may contain administrative decisions.
Downgrade `20260823_0012` is safe only before identity data or borrower-organization links are
relied upon. After use, prefer a forward-fix. A downgrade drops all new identity data and the new
application ownership column.

Configuration rollback must never enable local auth bypass in staging or production. There is no
worker or provider impact and no external provider action to reverse.

## Ownership and recovery permissions

Platform Engineering owns Keycloak/JWKS availability and schema deployment. Security/Identity
Operations owns user binding, activation, memberships, roles, and permissions. MoneyBee Support
may diagnose stable error codes but may not grant access. Recovery actions require the applicable
identity administration permission and an audit record.

## Known limitations

- Existing borrower records require a controlled organization backfill before removing subject
  compatibility.
- A live Keycloak staging browser/API test is still required with deployed Step 1A.
- Production metrics and alerts are delivered in Step 11.
- All live financial capabilities remain disabled.
