# MoneyBee API contract

Base URL: `https://api.moneybeeloans.com/api/v1`

Authentication uses bearer access tokens issued by `https://auth.codestra.co/realms/codestra`. Browser clients use Authorization Code + PKCE. Machine clients use Client Credentials. No client secret belongs in the frontend.

## Public intake
- `POST /leads` — requires `Idempotency-Key`.
- `POST /applications` — authenticated; requires `Idempotency-Key` and immutable consent-version evidence.

## Authenticated
- `GET /me`
- `GET /applications/{id}` — owner, operations, or admin.
- `POST /applications/{id}/submit` — owner or admin.
- `GET /applications/{id}/offers` — owner, operations, or admin.
- `GET /applications` — operations/admin only.

## Provider callbacks
- `POST /webhooks/{provider}` requires `X-Event-Id` and an HMAC-SHA256 hex digest in `X-MoneyBee-Signature` computed over the raw request body.

## Safety boundary
Lender submission and funding execution are disabled unless the production environment explicitly enables the relevant capability flags after legal, security, provider, and operations approval.
