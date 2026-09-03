# Phase 04 — Immutable installation, migration, identity and ingress

Phase ID: `MONEYBEE_PHASE_04_INSTALL`

Predecessor: Phase 03 `GO`.

Target: `49.12.145.107`

## Objective

Install the exact locked MoneyBee release, run the database migration once with the migration authority, start the application with restricted runtime authority, and make the intended HTTPS/OIDC surfaces available with all external effects disabled.

## 1. Pull the approved release

On the production host:

- authenticate to the approved registry using a least-privilege pull credential supplied outside Git and shell history;
- pull each component by the exact digest in the release lock;
- inspect the local manifest digest and verify it equals the lock;
- fetch the runtime repository only at the exact locked commit if a local evidence checkout is required;
- never run `git pull` on a moving branch as a deployment mechanism;
- never build application source on the production host;
- never deploy `latest` or a mutable tag.

Required image set:

```text
moneybee-api@sha256:...
moneybee-worker@sha256:...
moneybee-migrate@sha256:...
moneybee-marketing@sha256:...
moneybee-borrower@sha256:...
moneybee-lender@sha256:...
moneybee-admin@sha256:...
```

## 2. Bind secrets safely

Use the reviewed OpenBao/secret-store integration or approved root-readable secret files. Do not commit secrets or echo them into logs.

Validate presence—not values—for:

- PostgreSQL migrator and runtime credentials;
- Redis credentials/ACLs;
- field-encryption key map and active version;
- OIDC issuer/audience/client metadata;
- registry pull credential;
- Caddy/Kong/Keycloak service credentials where required;
- backup encryption material;
- monitoring/alert credentials.

External provider credentials are not required for the first production state and should remain absent or unused while their providers are disabled.

## 3. Render and verify runtime configuration

Render the locked production configuration and verify its checksum before apply.

Mandatory safety values:

```text
APP_ENV=production
AUTO_CREATE_SCHEMA=false
LOCAL_AUTH_BYPASS=false
LOCAL_IDENTITY_ENFORCEMENT=true
ENABLE_EXTERNAL_DELIVERY=false
LIVE_WRITES=false
ODOO_WRITE=false
CODESTRA_SDK_ENABLED=false
MIDDLEWARE_PROVIDER=disabled
BANK_PROVIDER=disabled
KYB_PROVIDER=disabled
CREDIT_PROVIDER=disabled
LENDER_PROVIDER=disabled
ESIGN_PROVIDER=disabled
EMAIL_PROVIDER=disabled
SMS_PROVIDER=disabled
OBJECT_STORAGE_MODE=disabled
MALWARE_SCAN_PROVIDER=disabled
PAYMENT_PROVIDER=disabled
```

Fail if any runtime file disagrees with the release lock.

## 4. One-shot database migration

Before migration:

- reverify backup and isolated restore evidence;
- confirm current database Alembic state;
- confirm the target migration head matches the release lock;
- verify the migration image digest;
- verify the API and worker are not starting with migrator credentials.

Run the migration as a one-shot job using `moneybee_migrator`.

Requirements:

```text
MIGRATION_IMAGE_DIGEST_MATCH=PASS
CURRENT_SCHEMA_RECOGNIZED=PASS
TARGET_HEAD_MATCH=PASS
MIGRATION_JOB_EXIT=0
ALEMBIC_CURRENT_EQUALS_LOCKED_HEAD=PASS
MIGRATION_CONTAINER_STOPPED_AFTER_COMPLETION=YES
API_WORKER_NEVER_RECEIVED_MIGRATOR_CREDENTIALS=YES
```

Do not put Alembic upgrade or schema creation in API/worker startup.

## 5. Start data and application services

Start only the reviewed release topology. Preserve existing platform services unless the locked plan explicitly replaces them.

Recommended order:

1. required private networks and volumes;
2. PostgreSQL/Redis dependencies or verified connections to existing approved services;
3. MoneyBee API;
4. MoneyBee worker;
5. marketing frontend;
6. borrower frontend;
7. lender frontend;
8. administrator frontend;
9. ingress routes;
10. monitoring hooks.

Verify:

- containers use exact locked digests;
- API/worker use the restricted `moneybee_app` role;
- services are unprivileged where supported;
- no unexpected host port is published;
- internal services are attached only to required networks;
- restart policies are appropriate;
- health checks do not require external providers;
- API and worker do not run migrations.

## 6. Keycloak/OIDC application

Apply MoneyBee identity configuration through the reviewed `appolon1908-hue/Keycloak` authority or its established deployment mechanism.

Required clients include the actual reviewed client IDs for:

```text
moneybee-borrower
moneybee-lender
moneybee-admin
MoneyBee server-to-server clients where approved
```

Verify:

- issuer is exactly `https://auth.codestra.co/realms/codestra`;
- Authorization Code + PKCE for browser applications;
- client credentials only for approved services;
- redirect URIs and web origins are exact and minimal;
- borrower, lender and admin clients are distinct;
- roles/scopes/audiences match backend checks;
- email verification/reset configuration is intact;
- no production administrator credential is exposed to the applications;
- cross-portal tokens are rejected;
- logout and session expiry work;
- no token is stored in a URL or unsafe browser storage.

Any identity drift is fixed in the Keycloak repository and released; do not make an undocumented realm-only patch.

## 7. Kong API ingress

Apply MoneyBee routes/plugins from the reviewed `appolon1908-hue/Kong` authority.

Required behavior:

- `api.moneybeeloan.com/api/v2` routes only to the locked MoneyBee API upstream;
- no route targets a stale container or branch build;
- forwarding headers are normalized and trusted only from the approved proxy chain;
- authentication is not bypassed for protected routes;
- public intake/webhook routes retain their intended rate limits/body limits/signature checks;
- request/correlation IDs propagate;
- upstream health checks use valid paths;
- internal admin/provider endpoints are not accidentally public;
- `/api/v1` compatibility policy matches the backend deprecation contract.

Validate the Kong plan before apply and save rollback configuration.

## 8. Caddy/TLS and public domains

Apply public hosts through the reviewed `appolon1908-hue/Caddy` authority.

Map:

```text
moneybeeloan.com           -> marketing
www.moneybeeloan.com       -> canonical redirect or marketing according to policy
app.moneybeeloan.com       -> borrower
lenders.moneybeeloan.com   -> lender
admin.moneybeeloan.com     -> administrator
api.moneybeeloan.com       -> Kong/API ingress
```

Verify:

- DNS resolves to the intended edge;
- TLS certificates are valid and trusted;
- HTTP redirects to HTTPS;
- HSTS/CSP/content-type/referrer/frame policy matches the application design;
- frontend assets use the correct API and OIDC authorities;
- no private backend port is exposed directly;
- admin/lender surfaces are not indexed when policy forbids indexing;
- rollback to the prior Caddy configuration is ready.

## 9. Core smoke tests

With external effects disabled, verify:

```text
/health/live=200
/health/ready=200
migration check=ok
Redis readiness=ok
OpenAPI loads
request and correlation IDs return
RFC problem responses work
marketing application loads
borrower application loads
lender application loads
administrator application loads
OIDC login and logout work per portal
cross-portal client token is rejected
unauthenticated protected requests are rejected
tenant/resource authorization is enforced
runtime database DDL attempt is denied
all effective provider capabilities remain disabled
```

Use synthetic test identities and a dedicated test tenant. Do not use a real customer, send a message, pull credit, submit to a lender or move money.

## 10. Installation rollback checkpoint

Record:

- previous and current image digests;
- previous and current Caddy/Kong/Keycloak configuration checksums;
- database backup reference and schema version;
- container/network/volume state;
- exact rollback commands;
- rollback validation result.

## Exit gate

Phase 04 is `GO` only when:

```text
ALL_IMAGE_DIGESTS_MATCH=PASS
SECRET_BINDING=PASS
CONFIGURATION_CHECKSUM=PASS
MIGRATION_ONE_SHOT=PASS
ALEMBIC_HEAD_MATCH=PASS
RUNTIME_DDL_DENIAL=PASS
API_AND_WORKER_HEALTH=PASS
ALL_FOUR_FRONTENDS=PASS
KEYCLOAK=PASS
KONG=PASS
CADDY_TLS_DOMAINS=PASS
TENANT_AND_PORTAL_ISOLATION=PASS
EXTERNAL_EFFECTS_DISABLED=PASS
INSTALLATION_ROLLBACK_CHECKPOINT=PASS
```

If any item fails, report `PHASE_04_NO_GO`. Roll back the unsafe component when required, fix the owning repository, rebuild/relock the release, and repeat. Do not bypass the failed gate.
