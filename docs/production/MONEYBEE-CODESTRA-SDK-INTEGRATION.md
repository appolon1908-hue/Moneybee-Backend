# MoneyBee Codestra SDK Production Integration

Branch authority: `integration/codestra-sdk-adapters-20260902`

MoneyBee must consume reviewed, versioned Codestra SDK artifacts and must not embed provider master credentials in browser applications.

Canonical path for shared platform capabilities:

MoneyBee frontend -> MoneyBee API -> Codestra SDK/client -> Caddy/Kong -> Middleware -> approved downstream integration.

Provider-specific backend adapters remain server-side and fail closed until their own staging, credential, reconciliation, observability, backup/restore, and controlled activation gates pass.

Required production gates:
- exact SDK version/source SHA/artifact hash
- Keycloak/OIDC authentication
- tenant context and correlation
- idempotency for consequential mutations
- webhook verification and replay protection
- unknown-outcome reconciliation before retry
- PostgreSQL/Redis recovery
- object storage and malware scanning paired for untrusted uploads
- zero Critical/High unresolved production issues
- staging E2E and production read-only canary
- SSH unchanged

External connectors remain disabled by default during certification.
