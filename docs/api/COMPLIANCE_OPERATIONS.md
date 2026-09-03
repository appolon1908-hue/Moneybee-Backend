# MoneyBee compliance operations API

Updated: 2026-09-02

This route surface exposes the existing adverse-action, commercial-financing disclosure, and commission-tax records through one typed operator and borrower contract. It does not send a legal notice, transmit a tax filing, activate a provider, or move funds.

## Canonical endpoints

| Method and path | Permission/ownership | Effect |
| --- | --- | --- |
| `GET /api/v2/admin/compliance/overview` | `application.read` | Counts records requiring acknowledgment, delivery evidence, TIN, or filing attention. |
| `GET /api/v2/admin/compliance/adverse-action-notices` | `application.read` | Paginated, filterable immutable notice snapshots. |
| `GET /api/v2/admin/compliance/commercial-financing-disclosures` | `application.read` | Paginated, filterable offer-disclosure snapshots. |
| `GET /api/v2/admin/compliance/commission-tax-records` | `commission.receipt.record` | Paginated tax-year aggregation records; exposes `tin_present`, never TIN or ciphertext. |
| `POST /api/v2/admin/compliance/commission-tax-records/generate` | `commission.receipt.record` | Idempotently recomputes tax-year records from authoritative commission splits. |
| `PATCH /api/v2/admin/compliance/commission-tax-records/{record_id}/tin` | `commission.receipt.record` | Stores an encrypted, write-only recipient TIN. |
| `PATCH /api/v2/admin/compliance/commission-tax-records/{record_id}/filing` | `commission.receipt.record` | Idempotently records evidence from an approved external filing process. |
| `GET /api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure` | Owning borrower/admin context | Returns the exact disclosure snapshot tied to the authorized application. |
| `POST /api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure/acknowledge` | Owning borrower/admin context | Records the authenticated subject as acknowledger; requires `Idempotency-Key`. |
| `POST /api/v2/admin/compliance/offers/{offer_id}/commercial-financing-disclosure/acknowledge` | `application.edit` | Administrative acknowledgment with authenticated actor and replay evidence. |

## Collection envelope

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

Limits are bounded from 1 through 200. Invalid pagination produces the repository's `application/problem+json` validation response.

## Mutation guarantees

- Generation and filing-evidence operations require an `Idempotency-Key`.
- A key replay with the same normalized request returns the original result.
- Reusing a key with a different request returns a conflict.
- Disclosure acknowledgment derives `acknowledged_by` from the authenticated principal and ignores any spoofed request body field.
- Filing evidence cannot silently overwrite a different existing filing reference.
- Domain change, audit evidence, and idempotent response evidence commit in one transaction.

## Sensitive-data guarantees

- TIN commands reject unknown fields.
- Plaintext TIN is encrypted through the repository's versioned field-encryption service.
- Plaintext TIN and encrypted ciphertext are absent from all API responses.
- Browser storage, query strings, logs, and analytics must not contain a TIN.

## Compatibility and evidence

The same router is mounted under `/api/v1` only as a hidden compatibility alias. Canonical OpenAPI remains `/api/v2` only. `scripts/sync_compliance_operator_manifest.py` and the generated endpoint catalog provide deterministic drift evidence.
