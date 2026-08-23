# Integration control plane

MoneyBee is the authoritative lending system. Codestra is the controlled
integration plane, and Odoo Community is a CRM projection only.

## Runtime flow

1. A MoneyBee write and its outbox event commit in the same database transaction.
2. The leased outbox worker verifies `crm.write` capability readiness.
3. The worker publishes a versioned event envelope to Codestra with OAuth 2
   client credentials and an idempotency key.
4. Codestra may project the event to Odoo, Klyrow, Telnexa, n8n, accounting, or
   another approved integration.
5. Provider failure never rolls back the original MoneyBee transaction. The
   outbox retries with bounded exponential backoff and moves to dead letter
   after its retry budget is exhausted.

Examples of the integration vocabulary include `lead.created.v1`,
`offer.received.v1`, and `funding.confirmed.v1`. Legacy internal event names
are normalized at the worker boundary.

## Inbound callbacks

`POST /api/v2/webhooks/codestra` requires:

- `X-Codestra-Message-Id`
- `X-Codestra-Timestamp` containing Unix seconds
- `X-Codestra-Signature` containing
  `HMAC-SHA256(secret, timestamp + "." + raw_body)`

The endpoint rejects expired timestamps, verifies the raw body before parsing,
deduplicates by provider and event ID, and commits the verified payload to the
durable `integration_inbox`. It deliberately does not mutate applications.
Approved domain handlers must validate any requested action during later inbox
processing.

`POST /api/v2/webhooks/middesk` independently verifies the documented
`X-Middesk-Signature-256` HMAC over the raw request body and writes the same
durable inbox. It also does not update verification state inline.

Operators can inspect sanitized inbox metadata at
`GET /api/v2/admin/integration-inbox` and the aggregate control-plane status at
`GET /api/v2/admin/integration-control-plane`.

## Odoo Community

The optional adapter supports Odoo 19 JSON-2 and an XML-RPC fallback for older
servers. Install `deploy/odoo-addons/moneybee_crm_bridge` in Odoo before
selecting `CRM_PROVIDER=odoo`. The bridge creates or updates contacts,
companies, and CRM opportunities through MoneyBee identifiers.

Odoo owns CRM activities and assignment. It does not own application,
underwriting, fraud, matching, offer, contract, funding, or commission state.
Manual Odoo stage changes do not update MoneyBee.

Odoo 19 JSON-2 uses bearer API keys and the optional `X-Odoo-Database` header
as documented by Odoo:
https://www.odoo.com/documentation/19.0/developer/reference/external_api.html

## Native financial providers

- Plaid remains a direct core-banking adapter.
- Middesk is available as the native KYB adapter. Its sandbox and production
  keys must be paired with the correct base URL.
- Experian Commercial is entitlement-configured. Endpoint paths and field
  mappings are required; the adapter intentionally refuses to guess them.
- Lender delivery remains governed by MoneyBee eligibility, program version,
  authorization, and capability rules even when Codestra carries transport.

Middesk authentication documentation:
https://docs.middesk.com/build/api-keys

## Activation

All providers default to `disabled`. Activation requires, in order:

1. approved contracts and data mappings;
2. secrets supplied outside source control;
3. successful provider health verification;
4. a READY provider connection record;
5. the relevant capability flag enabled by an authorized operator.

Do not put n8n or any provider directly on the MoneyBee database. Workflow
automation must call approved, authenticated APIs and pass normal domain
validation.
