# MoneyBee observability and secrets integration

Status: prepared for staging; not deployed from this repository.

## Stack roles

- Prometheus scrapes MoneyBee API metrics, exporters, and Blackbox probes.
- Blackbox Exporter probes public MoneyBee URLs and verifies required HSTS/CSP headers.
- Alertmanager receives MoneyBee service, security-header, TLS, API, Redis, and PostgreSQL alerts.
- Grafana should provision Prometheus, Loki, and Tempo datasources and import MoneyBee dashboards from these metrics.
- Loki receives JSON application logs from Docker or Alloy.
- Tempo receives OTLP traces from the collector once application tracing is enabled.
- OpenTelemetry Collector receives OTLP on `4317` and `4318`.
- Grafana Alloy can collect container logs and scrape MoneyBee API metrics where it is the selected agent.
- OpenBao stores MoneyBee runtime secrets and can provide transit encryption for future field-key rotation.

## MoneyBee files

- `deploy/observability/prometheus-moneybee.yml`
- `deploy/observability/blackbox-moneybee.yml`
- `deploy/observability/moneybee-alerts.yml`
- `deploy/observability/otel-collector-moneybee.yml`
- `deploy/observability/alloy-moneybee.river`
- `deploy/observability/openbao-moneybee-policy.hcl`

## Required internal scrape targets

Prometheus must run on a Docker network that can resolve:

- `moneybee-api:8000`
- `blackbox-exporter:9115`
- `node-exporter:9100`
- `cadvisor:8080`
- `postgres-exporter:9187`
- `redis-exporter:9121`
- `alertmanager:9093`

Do not expose `/metrics` publicly through `api.moneybeeloan.com`; scrape it on the internal Docker network.

## Required public probes

Blackbox probes must run against:

- `https://moneybeeloan.com`
- `https://app.moneybeeloan.com`
- `https://lenders.moneybeeloan.com`
- `https://admin.moneybeeloan.com`
- `https://api.moneybeeloan.com/health/live`
- `https://api.moneybeeloan.com/health/ready`

The security-header probe must fail when `Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options`, or `Referrer-Policy` is missing.

## OpenBao secret layout

Use non-secret references in Git and store live values in OpenBao:

```text
kv/moneybee/backend/DATABASE_URL
kv/moneybee/backend/REDIS_URL
kv/moneybee/backend/FIELD_ENCRYPTION_KEY
kv/moneybee/keycloak/OIDC_CLIENT_SECRET
kv/moneybee/codestra/CODESTRA_MIDDLEWARE_CLIENT_SECRET
kv/moneybee/providers/PLAID_SECRET
kv/moneybee/providers/ODOO_API_KEY
kv/moneybee/providers/MIDDESK_API_KEY
kv/moneybee/providers/EXPERIAN_CLIENT_SECRET
kv/moneybee/providers/DOCUSIGN_ACCESS_TOKEN
kv/moneybee/providers/SENDGRID_API_KEY
kv/moneybee/webhooks/PROVIDER_WEBHOOK_SECRETS_JSON
```

Never write provider secrets, SMTP passwords, OpenBao tokens, Keycloak secrets, or webhook secrets into Git, Docker labels, logs, traces, metrics, dashboards, or evidence files.

## Staging acceptance

Before production, capture evidence that:

- `/metrics` is reachable internally and blocked externally.
- Prometheus target `moneybee-api` is up.
- Blackbox probes pass for all public MoneyBee domains.
- Missing CSP/HSTS triggers `MoneyBeeSecurityHeadersMissing`.
- API 5xx simulation triggers `MoneyBeeApiElevated5xx`.
- Loki receives MoneyBee JSON logs with `request_id` and `correlation_id`.
- Tempo receives one synthetic trace for a borrower onboarding request.
- OpenBao policy can read only MoneyBee paths and cannot list unrelated product paths.
- Alertmanager routes critical MoneyBee alerts to the approved on-call receiver.

Provider activation remains blocked until each provider has credentials in OpenBao, staging health evidence, legal/security approval, and an explicit activation record.
