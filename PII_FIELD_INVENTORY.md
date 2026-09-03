# MoneyBee PII Field Inventory

Status reflects the reviewed hardening branch, not the currently deployed production release.

| Field/category | Classification | Current storage | Target protection | Authorized access | Audit / rotation |
|---|---|---|---|---|---|
| Commission payee tax identifier | Restricted government identifier | Versioned application ciphertext (`tax_tin_ciphertext`, `tax_tin_key_version`) | Keep encrypted; never return plaintext by default | Tax/compliance workflow only | Reveal must be explicitly authorized and audited; rotate by decrypt/re-encrypt batch with old key retained until verified |
| Bank provider access token | Restricted financial credential | Legacy production-derived schema contains encrypted ciphertext; reviewed model expects a credential reference | Migrate safely to a secret-provider reference after compatibility and provider retrieval tests | Banking integration service only | Audit credential retrieval metadata, never the token; retain versioned recovery path during migration |
| Bank account mask and balance data | Confidential financial PII | PostgreSQL plaintext fields | Mask account identifiers, enforce tenant authorization, encrypt fields if full identifiers are introduced | Borrower, authorized operations, underwriting | Audit access to detailed financial views |
| Borrower/lender names, email, phone, address | Confidential contact PII | PostgreSQL plaintext | Row/tenant authorization, minimization, masked operational views, encrypted backups | Subject and authorized staff | Audit administrative access and exports; encryption-key rotation does not apply to plaintext fields |
| Owners and ownership details | Confidential identity/business PII | PostgreSQL plaintext | Tenant-scoped authorization and minimization | Borrower and authorized underwriting/operations | Audit administrative access and exports |
| Uploaded documents | Restricted document content | Object-storage abstraction with quarantine/scan states in reviewed code; production object storage/scanner not enabled | Private encrypted object storage, quarantine, MIME/size validation, malware scan, authorized download | Subject and authorized reviewer | Audit upload, scan, acceptance, rejection, download; storage-key rotation via provider KMS process |
| Authentication subject/email | Confidential identity metadata | PostgreSQL plaintext | OIDC/local-auth production controls and tenant boundaries | Identity service and authorized admins | Audit login/admin actions; never log tokens or password material |

Open production blockers:

- The legacy bank-token ciphertext to credential-reference transition is not represented by a validated compatibility migration.
- Production object storage and malware scanning are not enabled or proven.
- A production PII reveal workflow with explicit reason and immutable audit evidence has not been demonstrated.
- Off-host encrypted backup custody and key separation have not been demonstrated.
