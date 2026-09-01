# MoneyBee reviewed OpenAPI snapshot changes

Updated: 2026-09-01

This review records the intentional contract changes introduced by the MoneyBee API and security remediation branch before regenerating the committed contract snapshots.

## Reviewed additions

- Complete paginated compliance operator APIs for adverse-action notices, commercial-financing disclosures and commission tax records.
- Borrower-owned commercial-financing disclosure read and idempotent acknowledgment.
- Administrator disclosure acknowledgment with authenticated actor attribution.
- Write-only encrypted commission-recipient TIN command.
- Idempotent commission tax filing-reference evidence.
- Compliance overview counts for records requiring operational attention.

## Reviewed schema hardening

- `StrictCommissionTaxRecordTinInput` rejects unknown fields and is intentionally distinct from the legacy compatibility command schema.
- `CommissionTaxRecordFilingInput` rejects unknown fields.
- Lender-program monetary update fields use exact decimal schemas.
- Lender bank-transaction amounts use exact decimal schemas.

## Compatibility decision

The legacy `CommissionTaxRecordTinInput` schema remains in the reviewed baseline for existing compatibility endpoints. The strict canonical compliance endpoint uses `StrictCommissionTaxRecordTinInput`; the two schemas are deliberately not collapsed or silently renamed.

Reviewed strict schema digest before snapshot regeneration:

```text
StrictCommissionTaxRecordTinInput
sha256:87a6fa2b70690f68b1a57e3598acf16389ba2b906bdabbe229311666ff4c4f2f
```

The temporary snapshot job may update only existing `openapi.json` entries and reviewed manifest hashes. It must refuse path/schema removals and any change outside the contract snapshots.
