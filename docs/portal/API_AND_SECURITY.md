# MoneyBee portal API and webhook security

Status: implementation branches only; not deployed and no live capability is enabled.

## API boundary

All browser portals use `/api/v2`. Tenant scope is derived from the locally resolved
MoneyBee principal, never from a borrower or lender identifier supplied by the browser.

## Portal capability controls

Document uploads require `documents.secure_upload` and a provider-ready object-storage
connection. Uploaded objects enter a quarantine path and create a `DocumentUploaded`
event for scanning; they cannot be downloaded until marked `CLEAN` or `APPROVED`.

Bank connections, credit pulls, lender submissions, e-signature sends, email, and SMS
retain their existing fail-closed capability flags. These implementation branches do not
enable any of them.

## Webhook contract

Generic provider callbacks use:

- `X-MoneyBee-Timestamp`
- `X-MoneyBee-Signature: sha256=<hex HMAC>`
- `X-Provider-Event-ID`

The signature input is `<timestamp>.<raw request body>`. Providers must be explicitly
allowlisted and configured through `PROVIDER_WEBHOOK_SECRETS_JSON`. Events outside the
timestamp tolerance fail closed. A reused event ID with a different payload hash is a
conflict. Valid events are stored in the durable inbox and receipt ledger without directly
changing lending state.

Canonical provider callback aliases are available for integrations that need stable
vendor-facing URLs:

| Provider | Endpoint | Secret key |
| --- | --- | --- |
| Lender adapters | `POST /api/v2/webhooks/lenders/{lender_id}` | `lender` |
| DocuSign | `POST /api/v2/webhooks/docusign` | `docusign` |
| Odoo actions | `POST /api/v2/webhooks/odoo/actions` | `odoo` |
| SendGrid | `POST /api/v2/webhooks/communications/sendgrid` | `sendgrid` |
| Twilio | `POST /api/v2/webhooks/communications/twilio` | `twilio` |
| n8n workflows | `POST /api/v2/webhooks/n8n` | `n8n` |
| Experian | `POST /api/v2/webhooks/experian` | `experian` |

The generic route remains available at `POST /api/v2/webhooks/providers/{provider}` for
approved providers that do not need a dedicated alias.

Example signing flow:

```sh
body='{"event_id":"evt_123","event_type":"submission.status_changed","aggregate_id":"app_123"}'
timestamp="$(date +%s)"
signature="$(printf '%s.%s' "$timestamp" "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | awk '{print $2}')"

curl -X POST "$BASE_URL/api/v2/webhooks/docusign" \
  -H "Content-Type: application/json" \
  -H "X-MoneyBee-Timestamp: $timestamp" \
  -H "X-MoneyBee-Signature: sha256=$signature" \
  -H "X-Provider-Event-ID: evt_123" \
  --data "$body"
```

Operational rules:

- Use one high-entropy secret per provider key.
- Rotate by deploying the new secret and replaying a signed synthetic event before cutting provider traffic.
- Treat `202` with `duplicate: true` as successful replay handling.
- Treat `409 WEBHOOK_EVENT_ID_CONFLICT` as a provider or signing incident; do not requeue blindly.
- Review `/api/v2/admin/webhook-receipts` before replaying production events.

## Added permission codes

Production roles should be reviewed and explicitly granted only the permissions they need:

- `documents.secure_upload`
- `lender.bank.read`
- `lender.decision.create`

No wildcard role is introduced by these branches.
