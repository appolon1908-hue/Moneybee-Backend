# Provider Adapter Activation Runbook

MoneyBee provider adapters are fail-closed. Configuration selects an adapter, while
database capability flags and a `READY` provider connection authorize its use. Both
conditions are required before a live route can call a vendor.

## Prepared adapters

| Domain | Adapter | Default | Capability |
|---|---|---:|---|
| Banking | Plaid | disabled | `bank.live_connection` |
| CRM | Generic bearer HTTP | disabled | `crm.write` |
| KYB | Generic bearer HTTP | disabled | `kyb.live_verification` |
| Credit | Generic bearer HTTP | disabled | `credit.live_pull` |
| Lenders | Generic bearer HTTP | disabled | `lenders.live_submission` |
| E-sign | DocuSign | disabled | `esign.live_send` |
| Email | SendGrid | disabled | `communications.live_email` |
| SMS | Twilio | disabled | `communications.live_sms` |
| Documents | Private S3-compatible storage | disabled | no upload route yet |

No mock adapter is selectable in production configuration.

## Activation order

1. Select a provider in environment configuration.
2. Install credentials through the approved secret manager; never commit them.
3. Configure `FIELD_ENCRYPTION_KEY` before enabling banking.
4. Create or update the provider-connection record and verify health.
5. Run sandbox or staging contract tests.
6. Enable only the matching capability flag.
7. Execute one controlled canary and reconcile the provider result.
8. Establish alerting and rollback ownership before increasing traffic.

Disabling a capability immediately closes the corresponding live mutation route.

## Plaid banking flow

1. The authenticated borrower requests a Link session.
2. The backend requires `bank.live_connection` and creates a short-lived Link token.
3. Plaid Link returns a temporary public token to the browser.
4. The browser sends that token to MoneyBee.
5. MoneyBee exchanges it server-side and encrypts the access token with Fernet.
6. Account and cursor-based transaction synchronization write normalized records.
7. Bank analysis stores derived metrics without exposing the provider access token.
8. Verified Plaid webhooks create an idempotent receipt and durable outbox event.

Plaid access tokens, API secrets, and webhook JWTs are never returned by MoneyBee APIs.

## Object storage

The S3-compatible adapter writes private objects with server-side AES-256 encryption
and creates download links with a maximum 15-minute lifetime. No document upload
route is enabled by this adapter pack. Before adding one, require malware scanning,
MIME and size enforcement, quarantine state, object-key isolation, document
authorization, retention policy, and audit evidence.

## Vendor-native work still required

The generic CRM, KYB, credit, and lender adapters require the selected vendors'
schemas, authentication contracts, idempotency behavior, webhook verification, error
taxonomy, rate limits, and sandbox certification. Enabling a generic adapter before
those mappings are approved is not a production launch.

## Rollback

1. Disable the capability flag.
2. Stop new outbox delivery for the affected provider.
3. Preserve receipts and integration evidence.
4. Reconcile provider-side state.
5. Rotate or revoke credentials if compromise is suspected.
6. Re-enable only after the failed canary or incident is resolved.
