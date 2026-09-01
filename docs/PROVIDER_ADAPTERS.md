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
| Payments | Stripe or PayPal | disabled | `payments` / `payouts` |
| Bank credential store | Self-hosted Vault (KV v2) | disabled | `bank.credential_store_certified` |

No mock adapter is selectable in production configuration.

## Activation order

1. Select a provider in environment configuration.
2. Install credentials through the approved secret manager; never commit them.
3. Configure `FIELD_ENCRYPTION_KEYS_JSON` (a `{"<version>": "<fernet key>"}` map)
   and `FIELD_ENCRYPTION_ACTIVE_KEY_VERSION` before enabling any capability
   that persists an encrypted field in MoneyBee's own database (e.g.
   commission-tax-record TINs). Ciphertext is prefixed with the key version
   it was encrypted under (`<version>:<token>`), so a new key can be added
   and made active without invalidating values already encrypted under the
   previous one - decrypt still resolves whichever version the ciphertext
   names. See `app/encryption.py`'s `rewrap_secret()` for migrating a stored
   value onto the newly active version. Banking does *not* use this - Plaid
   access tokens go through the external credential store instead (below),
   never MoneyBee's own database, encrypted or otherwise. Configure
   `BANK_CREDENTIAL_STORE_PROVIDER`/`VAULT_*` before enabling banking.
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
5. MoneyBee exchanges it server-side for a Plaid access token, then immediately
   writes that access token into the external credential store
   (`app/integrations/vault.py`, self-hosted HashiCorp Vault's KV v2 API) and
   persists only the opaque reference it returns
   (`BankProviderState.credential_reference`) — the raw access token is never
   written to MoneyBee's own database, not even encrypted (`app/banking.py`).
6. Each sync resolves the access token back through the credential store,
   uses it for that one request, and lets it go out of scope — it is never
   cached or persisted server-side beyond the single request.
7. Account and cursor-based transaction synchronization write normalized records.
8. Bank analysis stores derived metrics without exposing the provider access token.
9. Verified Plaid webhooks create an idempotent receipt and durable outbox event.

Plaid access tokens, API secrets, and webhook JWTs are never returned by MoneyBee APIs.
`BANK_CREDENTIAL_STORE_PROVIDER=vault` requires a self-hosted, initialized, and
unsealed Vault instance reachable at `VAULT_ADDR` — provisioning and unsealing
Vault is an operator task, not something automated here (see `deploy/README.md`).

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

The Stripe/PayPal payment adapters additionally need a business decision this repo
cannot make on its own: whether MoneyBee originates transfers itself (this adapter's
purpose) or stays a system of record while lenders wire funds directly, and if the
former, how payees get onboarded (Stripe Connect account, PayPal email) before a
`send_payout` call has a real `destination` to target. `app/admin_routes.py`'s
funding endpoints record a `provider_reference` string today regardless of which
model is chosen - wiring this adapter into that flow is a separate, deliberate change
once that decision is made, not implied by the adapter existing.

## Rollback

1. Disable the capability flag.
2. Stop new outbox delivery for the affected provider.
3. Preserve receipts and integration evidence.
4. Reconcile provider-side state.
5. Rotate or revoke credentials if compromise is suspected.
6. Re-enable only after the failed canary or incident is resolved.
