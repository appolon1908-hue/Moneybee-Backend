# Identity and Tenancy API Contract

All authenticated `/api/v2` requests use OIDC bearer tokens issued by
`https://auth.codestra.co/realms/codestra`. The backend, not frontend route guards, is the
authorization authority.

## Tenant selection

When a user has one active organization, it is selected automatically. When a user has more than
one, send `X-Organization-ID` with an organization UUID belonging to the user. A token
`organization_id`/`org_id` claim may request a tenant but does not grant membership.

## `GET /api/v2/me`

Returns local `user_id`, immutable OIDC `issuer` and `subject`, organization choices, the active
organization, membership types, database-backed roles and permissions, and borrower/lender IDs.
It does not return tokens, secrets, or rely on email as an identity key.

## Stable errors

| HTTP | Code | Meaning |
| --- | --- | --- |
| 401 | `AUTHENTICATION_REQUIRED` | No bearer token was supplied. |
| 401 | `INVALID_ACCESS_TOKEN` | Signature or required JWT claims failed validation. |
| 401 | `IDENTITY_NOT_BOUND` | `(issuer, subject)` has no approved local binding. |
| 403 | `USER_DISABLED` | The local user is disabled. |
| 403 | `MEMBERSHIP_INACTIVE` | No active organization membership is available. |
| 403 | `TENANT_SELECTION_REQUIRED` | Multiple organizations exist and none was selected. |
| 403 | `TENANT_ACCESS_DENIED` | The selected organization is not an active membership. |
| 403 | `PERMISSION_DENIED` | The local role set lacks the endpoint permission. |
| 403 | `RESOURCE_ACCESS_DENIED` | The tenant does not own the requested resource. |
| 503 | `IDENTITY_PROVIDER_UNAVAILABLE` | JWKS/identity provider retrieval failed. |

The response body uses FastAPI's stable nested envelope:

```json
{
  "detail": {
    "code": "TENANT_ACCESS_DENIED",
    "message": "The user does not belong to the selected organization."
  }
}
```

Identity GET requests do not require `Idempotency-Key` or `If-Match`, do not mutate financial
state, and emit no domain event. Borrower access requires active borrower membership plus
application organization ownership. Lender access requires active lender membership plus lender
submission ownership. MoneyBee staff permissions apply only through active MoneyBee membership.
