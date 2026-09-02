# Observability contract

MoneyBee emits structured request logs with request/correlation identifiers and exposes application metrics through the reviewed monitoring integration. Telemetry must never contain plaintext PII, credentials, authorization headers, provider payloads, document bodies, or database URLs.

Actionable alerts are required for: readiness failure, PostgreSQL pool exhaustion, Redis/rate-limit failures, provider timeout/unknown outcome, repeated webhook validation failure, outbox/inbox backlog age, dead events, operational exceptions, document scan failure, payment reconciliation, and missing worker heartbeat. Alerts identify the release SHA and operation ID and route to an accountable operator. Dashboard presence alone is not certification; staging must prove each critical signal and alert path before `OBSERVABILITY_STATUS=PASS`.
