# Phase 06 — Write-disabled production canary, observability and rollback proof

Phase ID: `MONEYBEE_PHASE_06_GO_LIVE`

Predecessor: Phase 05 `GO`.

Target state: `LIVE_WITH_EXTERNAL_EFFECTS_DISABLED`.

## Objective

Declare the MoneyBee core software live only after an exact-release canary proves HTTPS, identity, tenancy, API, frontends, database authority, integrations, observability and rollback under the write-disabled production configuration.

## 1. Reverify production authority

Immediately before canary:

- rerun the release-lock verifier;
- verify installed image digests and OCI source/revision labels;
- verify runtime, Caddy, Kong, Keycloak and observability checksums;
- verify Alembic head;
- verify backup and isolated restore evidence is still current;
- verify rollback artifacts remain available;
- verify every initial external-effect capability is disabled;
- record the UTC canary start, release ID and operator/change identity.

Any mismatch is `NO_GO`.

## 2. Public surface canary

From at least one external vantage point and the server/private network where appropriate, verify:

```text
moneybeeloan.com
www.moneybeeloan.com
app.moneybeeloan.com
lenders.moneybeeloan.com
admin.moneybeeloan.com
api.moneybeeloan.com/api/v2
```

For each surface capture:

- DNS result;
- TLS chain, hostname and expiry;
- HTTP status and redirects;
- response/security headers;
- release/source identifier where exposed safely;
- page/application load result;
- API health/readiness and OpenAPI checksum where applicable;
- synthetic login result for the correct portal;
- cross-portal and unauthenticated denial result;
- latency and error evidence;
- corresponding metrics/logs/traces.

Do not expose internal health details or secrets publicly.

## 3. Core functional canary

Using dedicated synthetic identities and tenant:

- authenticate borrower, lender and administrator through their correct clients;
- verify role, active organization and portal navigation;
- exercise safe read paths for products, application status, requirements, timeline, offers, conditions, compliance and finance as authorized;
- exercise an approved internal-only idempotent mutation and exact replay;
- prove a changed request with the same key conflicts;
- prove unauthorized cross-tenant resource IDs fail closed;
- prove provider-dependent operations return disabled/unavailable without contacting a provider;
- prove runtime database DDL remains denied;
- prove API/worker do not run migrations;
- verify worker/outbox/inbox/reconciliation state is healthy and no unexpected delivery occurs.

## 4. Negative safety canary

Explicitly test that the production release cannot perform an external effect in its initial state:

```text
live credit pull -> denied/unavailable
live lender submission -> denied/unavailable
DocuSign send/void -> denied/unavailable unless using a strictly isolated fake path
funding/payment/payout -> denied/unavailable
tax filing -> no transmission path
email/SMS -> denied/unavailable
Odoo production write -> denied/unavailable
n8n production delivery -> denied/unavailable
object-storage live upload -> denied/unavailable
malware-scanner external action -> denied/unavailable
Codestra SDK command -> denied/unavailable
live dialing -> denied/unavailable
```

The tests must not invoke the actual provider to prove denial. Use capability/readiness checks and local fail-closed validation.

## 5. Observability canary

Confirm that:

- Prometheus sees all required MoneyBee targets as healthy;
- Grafana dashboards show the exact release ID/source SHA;
- Loki receives structured API/worker/edge logs with request/correlation IDs;
- Tempo receives expected synthetic traces;
- Blackbox probes cover all public domains;
- PostgreSQL, Redis, container and host exporters are healthy;
- no secret/TIN/token appears in sampled logs/traces;
- alert rules load without error;
- a controlled test alert routes to the approved administrator/escalation channel;
- alert recovery/resolve behavior works;
- unexpected capability activation alert is present and testable without activating a real provider.

## 6. Soak and stability evidence

Observe the exact release for the approved soak period. The evidence must cover:

- container restarts and health transitions;
- request rate, latency and errors;
- CPU, memory, disk, inode and network headroom;
- database connections, locks and long transactions;
- Redis memory/evictions;
- worker queue depth/age;
- outbox/inbox/reconciliation growth;
- identity and ingress errors;
- TLS/probe continuity;
- unexpected external-effect attempts;
- alert noise/actionability.

A soak is not complete if monitoring is blind or the release head/digest changes during observation.

## 7. Rollback proof

Prove rollback without relying on an emergency source build.

Required proof:

1. validate the previous release images remain pullable by digest;
2. validate the previous runtime configuration checksum and manifests;
3. validate database compatibility or the documented restore/forward-recovery plan;
4. perform rollback in staging or an isolated production-like environment;
5. verify prior health, identity, API and frontend surfaces;
6. verify the new release can be re-applied from the lock;
7. record commands, duration, result and decision authority.

When policy permits a controlled production rollback exercise, use only a non-disruptive method approved by the change owner. Otherwise staging/isolation evidence must be explicit and current.

## 8. Rollback triggers

Rollback or disable the affected component when any threshold approved in the release plan is breached, including:

- readiness failure or crash loop;
- migration/schema mismatch;
- authentication/authorization/tenant-isolation failure;
- sustained error or latency breach;
- data-integrity or financial-ledger defect;
- unexpected external effect;
- secret exposure;
- queue/reconciliation growth beyond safe limits;
- database/Redis instability;
- public TLS/routing failure;
- monitoring blindness or inability to alert;
- source/digest/config drift;
- inability to execute the documented rollback.

Do not continue activation while a rollback trigger is active.

## 9. Production declaration

MoneyBee may be declared live only as:

```text
PRODUCTION_STATE=LIVE_WITH_EXTERNAL_EFFECTS_DISABLED
```

This means:

- public marketing, borrower, lender and admin applications are available;
- Keycloak login and portal separation work;
- API and internal workers are healthy;
- database and Redis are live under least privilege;
- safe internal/domain operations and read surfaces work;
- observability and rollback are proven;
- external communications, providers, filings and money movement remain disabled.

It does not mean every provider is activated.

## Exit gate

Phase 06 is `GO` only when:

```text
RELEASE_LOCK_AND_INSTALLED_DIGESTS=PASS
PUBLIC_DOMAINS_AND_TLS=PASS
KEYCLOAK_LOGIN_LOGOUT_AND_PORTAL_ISOLATION=PASS
API_HEALTH_READINESS_OPENAPI=PASS
ALL_FRONTENDS=PASS
TENANT_RESOURCE_AUTHORIZATION=PASS
IDEMPOTENCY_AND_CONFLICT_BEHAVIOR=PASS
RUNTIME_DDL_DENIAL=PASS
EXTERNAL_EFFECT_NEGATIVE_CANARY=PASS
METRICS_LOGS_TRACES_PROBES_ALERTS=PASS
SOAK=PASS
ROLLBACK_PROOF=PASS
SOURCE_RUNTIME_DRIFT=PASS
PRODUCTION_STATE=LIVE_WITH_EXTERNAL_EFFECTS_DISABLED
```

If any item fails, report `PHASE_06_NO_GO`, preserve evidence, roll back or contain the affected component, repair the owning repository, publish a new release lock and repeat from the necessary predecessor phase. Never bypass the failed gate.
