# Compliance Records Security Contract

This document defines the review-time security boundary for MoneyBee's adverse-action notices, commercial-financing disclosures, and commission tax records.

## Authority boundary

- The backend is the sole authority for permissions, calculations, persistence, state transitions, and audit attribution.
- A commercial-financing disclosure acknowledgment must be attributed from the authenticated principal. Client-supplied operator identifiers are not authoritative.
- Taxpayer identification numbers are write-only inputs. API responses expose only whether a TIN is present; they never return plaintext or ciphertext.
- Generated compliance records do not activate email, SMS, lender submission, filing, funding, or any other external delivery capability.

## API boundary

The canonical contract is `/api/v2`. The OpenAPI manifest and generated endpoint catalog must match the implementation at the exact pull-request head. Compatibility `/api/v1` routes remain excluded from the canonical schema.

## Validation boundary

The same behavior must pass in both supported test modes:

1. local auto-created SQLite schema;
2. migrated PostgreSQL schema with `AUTO_CREATE_SCHEMA=false`.

Unit tests may isolate pure rendering from database foreign-key enforcement only when separate integration tests already prove persistence against real parent records. Capability tests must reuse the schema's globally unique capability row and deliberately bind it to the active test environment rather than insert a duplicate key.

## Activation boundary

This change is source-side only. It does not merge the pull request, deploy a container, enable a provider, deliver a notice, file a tax form, acknowledge a production disclosure, or move money.
