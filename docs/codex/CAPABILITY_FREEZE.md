# MoneyBee Capability Freeze

These capabilities must remain disabled during the complete implementation program:

credit.live_pull = false

lenders.live_submission = false

esign.live_send = false

funding.live_confirmation = false

payments = false

payouts = false

documents.malware_scan_certified = false

## Rules

Code may be implemented while the capability remains disabled.

Provider adapters may be configured while the capability remains disabled.

Sandbox certification may occur while the production capability remains disabled.

No migration may enable these.

No CI workflow may enable these.

No staging or production deployment may implicitly enable these.

No readiness computation may enable these.

No UI action may silently enable these.

Capability activation requires a separate post-certification approval process.

