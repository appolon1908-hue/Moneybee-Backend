# MoneyBee API conventions

Updated: 2026-09-01

These conventions apply to the FastAPI application and every browser client consuming it.

## Versioning and contract authority

- `/api/v2` is the canonical REST prefix.
- `/api/v1` is a compatibility alias, hidden from OpenAPI and returned with deprecation/sunset headers.
- `openapi.json` and the generated `docs/API_ENDPOINT_CATALOG.md` are contract artifacts. The catalog must be regenerated from the application and committed with no drift.
- Every new operation must have a unique `operation_id`, explicit request/response schema, documented authorization and representative tests.

## Authentication, tenancy and authorization

- Authenticated endpoints verify an OIDC bearer token and resolve a local MoneyBee principal.
- Tenant selection uses the validated active organization and `X-Organization-ID` only through the centralized client and backend identity layer.
- A hidden or disabled frontend action is never authorization. The backend repeats membership, permission and resource-ownership checks.
- Administrative compliance endpoints require either `application.read`, `application.edit`, or `commission.receipt.record` as appropriate.
- Actor identity is derived from the authenticated principal. Client-supplied actor/user/operator identifiers are not authoritative.

## Request context

The centralized frontend client sends:

- `X-Request-ID`
- `X-Correlation-ID`
- `Authorization`, when authenticated
- `X-Organization-ID`, when an organization is selected
- `Idempotency-Key`, when the operation requires replay protection
- `If-Match`, when an optimistic version precondition is required

The API returns request and correlation IDs in response headers. Logs, audit events and durable integration records should preserve the relevant identifier without logging secrets.

## Error contract

Application errors converge on an `application/problem+json` document:

```json
{
  "type": "https://api.moneybeeloan.com/problems/conflict",
  "title": "Conflict",
  "status": 409,
  "detail": "The request conflicts with current resource state.",
  "instance": "/api/v2/resource",
  "request_id": "opaque-request-id",
  "code": "CONCURRENT_MODIFICATION",
  "context": {}
}
```

Validation failures use status 422 and include structured errors. Internal errors never return a stack trace, SQL text, credentials or provider secrets.

## Monetary and temporal values

- Authoritative money uses `Decimal`/database numeric values, never binary floating point.
- JSON responses serialize authoritative decimals as strings unless an existing documented schema explicitly uses integer minor units.
- Currency is an ISO 4217 code where a resource can support multiple currencies.
- Timestamps are UTC RFC 3339 values. Idempotent first responses and replays must preserve equivalent normalized serialization.
- IDs are UUIDs or an already-established opaque provider reference; clients must not infer meaning from an identifier.

## Collection queries

- Filter and sort values are explicitly declared and validated; client values are never interpolated into SQL.
- The new compliance collections use `items`, `total`, `limit`, `offset` and `has_more`.
- Default and maximum limits must be bounded. The compliance maximum is 200.
- Equivalent collections should use the repository’s existing canonical page shape rather than introduce an undocumented alternative.

## Idempotent mutations

Operations with financial, compliance, integration or irreversible effects require or support `Idempotency-Key` as declared by their endpoint contract.

The persisted record includes:

- authenticated actor
- canonical route/operation
- idempotency key
- normalized request hash
- response status/body
- creation timestamp

Rules:

1. Same actor, route, key and request hash returns the original result.
2. Reusing the key with a different normalized request returns 409.
3. A replay must not create a second domain, audit, ledger, outbox or provider record.
4. The frontend must not automatically retry a financial/compliance mutation with a new key after an ambiguous failure.

## Concurrency and state transitions

- Route handlers do not accept arbitrary target state from a client unless the domain service validates the transition.
- Use row locks, optimistic versions, unique constraints and single transactions according to the resource.
- State change plus audit/idempotency/ledger/outbox evidence must commit atomically.
- External provider calls should occur after durable intent is committed, normally through the outbox/worker path.

## Sensitive data

- Secrets are supplied by approved runtime secret stores, never committed to Git.
- TIN is a write-only input encrypted by the backend. Responses expose only `tin_present`.
- Bank access material is referenced through the approved encrypted credential-store abstraction.
- Tokens, TINs, account credentials and provider secrets must not appear in URLs, analytics, exceptions or normal application logs.

## Capability gates

A configured route does not imply an active external provider. Live behavior requires both a selected/configured provider and the corresponding enabled capability. Disabled, unavailable or degraded capability checks fail closed and return an explicit problem response.

Repository CI must keep external delivery, credit pulls, lender submission, e-sign, payment and related provider actions disabled.

## Frontend integration

- Screens import typed functions from `packages/api-client`; they do not call `fetch` directly.
- `VITE_API_BASE_URL` must end in `/api/v2`.
- The frontend contract workflow checks out an exact backend ref, exports OpenAPI, runs route drift validation, typechecks, tests and builds all applications.
- The frontend must display backend-provided terms, calculations and legal text without recomputing or rewriting them.
