# Phase 05 — Integration synchronization and end-to-end validation

Phase ID: `MONEYBEE_PHASE_05_INTEGRATIONS`

Predecessor: Phase 04 `GO`.

Production mode: software live, external effects still disabled.

## Objective

Prove that MoneyBee, identity, ingress, middleware, ERP, automation, SDK, secrets and observability agree on exact contracts, tenants, correlation/idempotency rules and failure behavior. Synchronize repository authority with the installed runtime without enabling external business effects.

## 1. Create the integration authority ledger

For every integration, record:

```text
source repository
exact source SHA
runtime component/image digest
source endpoint
consumer endpoint
identity/client ID
audience/scope/role
network path and TLS/mTLS policy
request and response schema/version
idempotency identity
correlation/request ID behavior
retry policy
ambiguous-outcome policy
inbox/outbox/reconciliation record
capability flag
initial activation state
owner and rollback
```

Missing authority or conflicting contracts are `NO_GO`.

## 2. MoneyBee frontend ↔ backend

Verify each application uses the exact installed API contract:

- frontend contract lock equals installed backend source SHA;
- runtime OpenAPI checksum equals the release lock;
- all typed client operations resolve to existing `/api/v2` routes;
- no direct browser call reaches Middleware, Odoo, n8n, database, OpenBao or a provider;
- API base URLs and OIDC issuer are correct for production;
- request IDs, correlation IDs, organization IDs, idempotency keys and version preconditions are sent by the shared client;
- authoritative monetary and legal values are rendered without client recomputation;
- offline/ambiguous mutation handling does not create a new key or blind retry;
- compliance pagination and partial endpoint failures remain usable;
- browser bundles contain no service secrets.

## 3. MoneyBee ↔ Keycloak

Run synthetic identity tests for borrower, lender and administrator users:

```text
registration policy
email verification boundary
password reset boundary
login + PKCE
logout
session expiration
multi-tab/session invalidation where supported
protected deep link restoration
issuer/audience/algorithm validation
active organization context
role and permission mapping
borrower token rejected from lender/admin route
lender token rejected from borrower/admin route
admin route permission checks
service account scope restriction
```

No identity test may weaken the realm or expose administrator credentials.

## 4. MoneyBee ↔ Kong/Caddy

Validate from external and internal viewpoints:

- public domains terminate trusted TLS;
- path routing reaches the exact image digest;
- API version and deprecation headers are preserved;
- public intake rate limits work;
- webhook body/signature/timestamp controls remain intact;
- authenticated routes cannot be accessed through an alternate hostname/path;
- direct upstream host ports are not public;
- request/correlation headers arrive at MoneyBee and return to the client;
- security headers are present on frontends;
- error/status bodies are not replaced with misleading proxy success;
- health probes use valid paths and do not create false alerts.

## 5. MoneyBee ↔ Codestra SDK ↔ Middleware

Initial capability remains disabled. Validate the integration boundary without executing a live business command.

Required checks:

- installed SDK package resolves to exact locked SDK SHA;
- SDK is server-only and absent from browser bundles;
- `CODESTRA_SDK_ENABLED=false` is effective;
- `MIDDLEWARE_PROVIDER=disabled` is effective;
- capability endpoint/readiness reports disabled rather than successful;
- enabling only one prerequisite still fails closed;
- command context requires tenant, actor/service identity, source SHA, request/correlation ID, idempotency key and allowed capability;
- one-attempt mutation and operation read-back behavior are covered by tests;
- ambiguous outcomes create reconciliation evidence and block blind retry;
- Middleware destination routes and schemas are present in its owning repository before later activation;
- no direct provider credential is exposed to MoneyBee.

Use mock/sandbox or validation-only calls that cannot perform an external effect.

## 6. MoneyBee ↔ Odoo

Initial `ODOO_WRITE=false` and CRM provider disabled.

Validate repository and runtime agreement for:

- MoneyBee model/field mapping;
- organization/campaign mapping when applicable;
- application, offer, condition, funding and status event vocabulary;
- record identity and deduplication key;
- correlation ID and source reference;
- inbound callback authentication;
- outbox/inbox and replay policy;
- data minimization and sensitive-field exclusions;
- failure/reconciliation workflow;
- operator visibility and audit evidence.

Run a synthetic validation against an isolated test database or write-disabled adapter. Do not create or update a production Odoo business record during the initial release.

If mapping/module changes are required, implement them in `appolon1908-hue/Odoo`, test and merge them, rebuild/relock affected artifacts, then repeat this phase.

## 7. MoneyBee ↔ n8n

Initial n8n delivery remains disabled.

Validate:

- workflow IDs and versions are source-controlled in `appolon1908-hue/N8N`;
- production workflows are inactive until separately approved;
- webhook/callback URLs point to the intended protected endpoints;
- authentication, tenant, idempotency and correlation fields are preserved;
- test executions use synthetic data and cannot send email/SMS, dial, submit lenders, update Odoo or move money;
- retries do not duplicate MoneyBee commands;
- failures create explicit evidence and do not return false success;
- workflow secrets are referenced from the approved secret store and are not in Git/export JSON.

## 8. MoneyBee ↔ OpenBao

Validate the approved secret-management pattern:

- policy names and paths are source-controlled in `appolon1908-hue/Codestra-OpenBao`;
- API, worker, migrator, Caddy/Kong/Keycloak deploy components receive only necessary secrets;
- migrator database secret is not available to API/worker;
- provider credentials remain inaccessible while providers are disabled;
- tokens are short-lived/renewable according to policy;
- audit logging is enabled without logging secret values;
- seal/unseal/recovery operating evidence exists;
- revoked/rotated secret behavior is tested safely.

## 9. MoneyBee ↔ observability stack

Use the owning observability repositories for changes.

### Metrics

Prometheus must scrape or receive approved metrics for:

```text
API request rate/latency/status
health/readiness
worker queue depth and age
outbox/inbox status
integration retries and terminal failures
idempotency conflicts
reconciliation-required operations
PostgreSQL availability/connections/locks where approved
Redis availability/memory/evictions
container/host CPU, memory, disk and restarts
TLS/HTTP probes for all public MoneyBee surfaces
```

### Logs

Loki/Alloy must receive structured logs with component, environment, release ID, source SHA, request ID and correlation ID. Redact tokens, TIN, bank credentials, provider secrets and sensitive request bodies.

### Traces

Tempo/Telemetry must preserve trace/correlation context across edge, API, worker and approved integration hops without including secrets.

### Dashboards

Grafana should provide:

- MoneyBee production overview;
- API/worker health;
- database/Redis health;
- identity and ingress errors;
- integration outbox/inbox/reconciliation;
- compliance and financial operational health without exposing sensitive data;
- release/canary comparison and rollback indicators.

### Alerts

Alertmanager must route actionable alerts for:

- public surface down or TLS failure;
- readiness failure;
- error/latency threshold breach;
- worker queue age/depth;
- database/Redis failure or capacity risk;
- migration/schema mismatch;
- unexpected capability activation;
- external-effect attempt during write-disabled mode;
- reconciliation-required accumulation;
- backup failure or stale backup;
- container crash loop or disk exhaustion.

Test alert delivery through a safe test route and verify ownership/escalation.

## 10. Synthetic end-to-end workflow

Use a dedicated synthetic tenant and identities. Execute only operations that do not trigger an external effect:

1. load marketing site and retrieve public product/config data;
2. authenticate borrower through Keycloak;
3. create or use a synthetic internal application according to approved test policy;
4. verify tenant ownership, requirements, timeline and status endpoints;
5. authenticate lender and prove cross-tenant denial;
6. authenticate admin and inspect application/compliance/finance read surfaces;
7. verify an idempotent internal mutation using a synthetic record and replay;
8. verify a changed request with the same key conflicts;
9. verify provider-dependent commands fail closed;
10. verify outbox/inbox/reconciliation metrics and logs correlate to the test;
11. remove or mark synthetic data according to audit policy without deleting required evidence.

Do not use a real customer, real lender, real payment instrument, real TIN or real provider action.

## 11. Runtime/repository drift reconciliation

Compare the installed runtime against every locked repository authority:

```text
container image digest
OCI source/revision labels
runtime configuration checksum
Kong config checksum
Caddy config checksum
Keycloak plan/export checksum
OpenBao policy checksum
Odoo module/mapping version
n8n workflow version
Prometheus rules/scrape config
Grafana dashboard versions
Loki/Tempo/Alloy config
alert routing config
```

Any unexplained difference is `SOURCE_RUNTIME_DRIFT=FAIL`. Fix the owning repository, review, rebuild, update the release lock and redeploy the affected immutable component. Do not normalize drift by editing the server and leaving Git behind.

## Exit gate

Phase 05 is `GO` only when:

```text
FRONTEND_BACKEND_CONTRACT_SYNC=PASS
KEYCLOAK_IDENTITY_AND_PORTAL_SYNC=PASS
KONG_CADDY_ROUTE_AND_TLS_SYNC=PASS
SDK_MIDDLEWARE_BOUNDARY_WRITE_DISABLED=PASS
ODOO_MAPPING_WRITE_DISABLED=PASS
N8N_WORKFLOW_BINDING_DISABLED=PASS
OPENBAO_LEAST_PRIVILEGE=PASS
METRICS_LOGS_TRACES=PASS
DASHBOARDS_AND_ALERTS=PASS
SYNTHETIC_END_TO_END=PASS
SOURCE_RUNTIME_DRIFT=PASS
EXTERNAL_EFFECTS_DISABLED=PASS
```

A failure means `PHASE_05_NO_GO`. Keep core services in the safest stable state, fix the owning repository, rebuild/relock/redeploy the affected component and repeat the failed validation. Do not bypass the integration gate.
