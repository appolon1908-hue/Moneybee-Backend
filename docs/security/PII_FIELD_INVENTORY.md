# PII field inventory

This inventory describes repository models. Operational encryption and backfill evidence remains a server rollout gate.

| Model/table | Field/category | Classification | Current storage | Search requirement | Target protection | Reveal policy | Audit requirement |
|---|---|---|---|---|---|---|---|
| `leads` | name, email, phone | Confidential contact PII | plaintext compatibility columns | email/phone equality | versioned ciphertext plus keyed HMAC lookup during expand/backfill | masked by default; tenant-authorized reveal | actor, tenant, resource, category, reason, correlation ID |
| `owners` | name, email, phone | Restricted owner identity | plaintext compatibility columns | limited equality lookup | versioned ciphertext plus separate lookup token | underwriting/compliance permission only | every reveal and export |
| `public_intakes` | name, email, phone, message | Confidential intake PII | plaintext | dedupe/contact lookup | encrypt high-risk values; HMAC lookup where required | authorized operations only | administrative reveal/export |
| `users`, `user_accounts` | subject, email, display name | Identity metadata | plaintext | OIDC binding/email lookup | minimize; keyed lookup where encrypted | subject or identity administrator | privilege changes and administrative reads |
| `bank_provider_states` | provider credential | Restricted financial credential | versioned ciphertext/credential reference compatibility | provider reference only | secret-provider reference; versioned legacy decrypt | integration service only | credential retrieval metadata only |
| `bank_accounts`, balances, transactions | mask, balances, transaction narrative | Restricted financial PII | plaintext tenant rows | account and reconciliation lookup | tenant isolation, encryption for full identifiers | borrower and authorized finance roles | detailed access/export |
| `documents` | filename, storage key, content metadata | Restricted document PII | metadata in PostgreSQL, object in quarantine storage | storage-key lookup | private encrypted storage and generated keys | accepted/clean documents only | upload, scan, release, download, reject |
| `commission_tax_records` | taxpayer identifier | Restricted government identifier | versioned ciphertext | no plaintext search | `mbenc:<version>` ciphertext; separate HMAC only if lookup becomes necessary | tax/compliance permission only | every reveal; never plaintext in audit |
| provider/webhook records | provider IDs and payload metadata | Confidential integration data | minimized JSON/columns | provider-event dedupe | payload minimization and encrypted secrets | operations permission | processing, replay and reconciliation |

Encryption keys and `PII_LOOKUP_HMAC_KEY` are separate secrets. Neither belongs in Git, images, logs, telemetry, or audit details.
