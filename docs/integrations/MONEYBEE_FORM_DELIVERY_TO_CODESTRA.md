# MoneyBee public forms to Codestra middleware

## Reserved DNS name

Configure this dedicated ingress name for MoneyBee events:

```text
moneybee-events.codestra.co
```

Recommended DNS record after the middleware host is reverified:

```text
Type:  A
Name:  moneybee-events
Value: 65.109.65.169
TTL:   300
```

`65.109.65.169` is the current recorded Codestra middleware/Odoo/n8n host. Confirm its runtime inventory, reverse-proxy ownership, and port availability before changing DNS. The MoneyBee staging candidate `49.12.145.107` is the **source application host**, not the middleware DNS target.

Do not create an AAAA record until IPv6 routing and firewall policy are verified. Keep any CDN proxy disabled until OAuth, request-body integrity, client-IP handling, TLS, and webhook tests pass through it.

## Authoritative flow

```text
Public browser form
  -> MoneyBee API on 49.12.145.107
  -> authoritative MoneyBee database transaction
  -> durable MoneyBee outbox event
  -> MoneyBee worker, only when explicitly enabled
  -> https://moneybee-events.codestra.co/v1/events
  -> Codestra durable and deduplicated inbox
  -> allowlisted Odoo CRM projection
  -> signed receipt callback
  -> https://api.moneybeeloan.com/api/v2/webhooks/codestra/receipts
  -> MoneyBee durable inbox and delivery evidence
```

The browser must never post directly to Codestra or Odoo. Odoo, n8n, and Codestra must never write directly to MoneyBee PostgreSQL.

## MoneyBee public APIs that create CRM outbox events

```text
POST /api/v2/public/contact-requests
POST /api/v2/public/callback-requests
POST /api/v2/public/lender-partner-inquiries
POST /api/v2/public/referral-partner-inquiries
POST /api/v2/public/deal-submission-inquiries
```

The existing prequalification flow remains:

```text
POST /api/v2/public/prequalifications
```

Each accepted request stores its authoritative intake data, consent evidence, audit record, idempotency record, and outbox event in one transaction. The HTTP request does not wait for Odoo.

## Middleware ingress

```text
POST https://moneybee-events.codestra.co/v1/events
Content-Type: application/json
```

Required headers:

```text
Authorization: Bearer <Keycloak client-credentials access token>
Idempotency-Key: <MoneyBee outbox event UUID>
X-MoneyBee-Event-ID: <same event UUID>
X-MoneyBee-Timestamp: <Unix seconds>
X-MoneyBee-Signature: sha256=<HMAC-SHA256(timestamp + "." + exact raw body)>
X-Correlation-ID: <MoneyBee correlation ID, when available>
```

The middleware must verify the bearer token issuer, audience, expiry, and required scope. It must then verify the HMAC with a constant-time comparison before parsing or processing the event.

Recommended Keycloak machine client:

```text
Client ID: moneybee-middleware-publisher
Flow: service accounts / client credentials
Scope: moneybee.events.write
Audience: the approved Codestra middleware audience
Token URL: https://auth.codestra.co/realms/codestra/protocol/openid-connect/token
```

Store the client secret and the integration HMAC secret outside Git.

## Canonical event body

The transmitted body is canonical JSON with sorted keys and no insignificant whitespace. Its contract identifier is:

```text
moneybee.event-envelope.v1
```

Example:

```json
{
  "aggregate": {
    "id": "7fdad81e-a676-4cbd-9b1c-b629bb70e04c",
    "type": "public_intake",
    "version": 1
  },
  "causation_id": "f116af6e-e7ab-402b-b617-844cd61542d0",
  "contract": "moneybee.event-envelope.v1",
  "correlation_id": "f116af6e-e7ab-402b-b617-844cd61542d0",
  "event_id": "829bbfd1-546a-41bd-a797-b94ab5a8e325",
  "event_type": "public.contact_request.received.v1",
  "occurred_at": "2026-08-26T16:00:00+00:00",
  "payload": {
    "intake_type": "CONTACT_REQUEST",
    "moneybee_intake_id": "7fdad81e-a676-4cbd-9b1c-b629bb70e04c",
    "reference": "MB-CONTACT-123456789ABC"
  },
  "schema_version": 1,
  "source": "moneybee",
  "tenant_id": null
}
```

Supported public-intake event types:

```text
public.contact_request.received.v1
public.callback_request.received.v1
public.lender_partner_inquiry.received.v1
public.referral_partner_inquiry.received.v1
public.deal_submission_inquiry.received.v1
```

## Required middleware response

Return an HTTP success status only after the event has been durably stored in the Codestra inbox.

Recommended response:

```http
HTTP/1.1 202 Accepted
Content-Type: application/json
```

```json
{
  "receipt_id": "codestra-receipt-uuid",
  "event_id": "829bbfd1-546a-41bd-a797-b94ab5a8e325",
  "status": "accepted"
}
```

The pair `(source, event_id)` must be unique. Replaying the same event and identical body returns the original receipt. Reusing the event ID with a different body hash returns `409 Conflict` and creates a security/operational exception.

## Receipt callback

Codestra sends final delivery evidence to:

```text
POST https://api.moneybeeloan.com/api/v2/webhooks/codestra/receipts
```

Use these headers:

```text
X-Codestra-Message-Id: <stable receipt event ID>
X-Codestra-Timestamp: <Unix seconds>
X-Codestra-Signature: sha256=<HMAC-SHA256(timestamp + "." + exact raw body)>
Content-Type: application/json
```

The callback must be replay-safe and collision-safe. Receipt intake must not directly approve credit, submit to a lender, send an e-signature package, confirm funding, or move money.

## MoneyBee settings

Keep the initial values fail-closed:

```text
CODESTRA_MIDDLEWARE_BASE_URL=https://moneybee-events.codestra.co
CODESTRA_MIDDLEWARE_EVENT_PATH=/v1/events
CODESTRA_MIDDLEWARE_TOKEN_URL=https://auth.codestra.co/realms/codestra/protocol/openid-connect/token
CODESTRA_MIDDLEWARE_SCOPE=moneybee.events.write
CODESTRA_MIDDLEWARE_CLIENT_ID=<secret-managed value>
CODESTRA_MIDDLEWARE_CLIENT_SECRET=<secret-managed value>
CODESTRA_MIDDLEWARE_WEBHOOK_SECRET=<separate high-entropy integration secret>
MIDDLEWARE_PROVIDER=disabled
ENABLE_EXTERNAL_DELIVERY=false
```

After DNS, TLS, token, signature, deduplication, Odoo sandbox, receipt, retry, and rollback tests pass, a separate approved staging change may set:

```text
MIDDLEWARE_PROVIDER=codestra
ENABLE_EXTERNAL_DELIVERY=true
```

Do not enable production delivery from this branch.

## Reverse-proxy route

The exact middleware upstream port must come from a verified runtime inventory. A safe Caddy template is:

```caddyfile
moneybee-events.codestra.co {
    encode zstd gzip
    request_body {
        max_size 2MB
    }
    reverse_proxy 127.0.0.1:<VERIFIED_MIDDLEWARE_INGRESS_PORT>
}
```

For Kong, create a dedicated service and route with the host `moneybee-events.codestra.co` and path `/v1/events`. Apply authentication, scope validation, request-size limiting, rate limiting, correlation IDs, and an allowlist for the MoneyBee source host where operationally appropriate.

## Acceptance gates

```text
DNS_A_RECORD=PASS
TLS=PASS
KEYCLOAK_CLIENT_CREDENTIALS=PASS
TOKEN_AUDIENCE_AND_SCOPE=PASS
HMAC_SIGNATURE=PASS
STALE_TIMESTAMP_REJECTED=PASS
DUPLICATE_SAME_BODY=PASS
DUPLICATE_DIFFERENT_BODY=409
CODESRA_INBOX_DURABLE=PASS
ODOO_SANDBOX_UPSERT=PASS
ODOO_DUPLICATE_UPSERT=PASS
SIGNED_RECEIPT_CALLBACK=PASS
RETRY_AND_DEAD_LETTER=PASS
MANUAL_REQUEUE_AUDIT=PASS
EXTERNAL_DELIVERY_DEFAULT_OFF=PASS
ROLLBACK=PASS
```

No customer information should be sent until these gates are evidenced in staging.