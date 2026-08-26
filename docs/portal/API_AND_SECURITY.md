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

## Added permission codes

Production roles should be reviewed and explicitly granted only the permissions they need:

- `documents.secure_upload`
- `lender.bank.read`
- `lender.decision.create`

No wildcard role is introduced by these branches.
