# MoneyBee–Codestra connector SDK integration

Updated: 2026-09-02

## Immutable dependency

MoneyBee installs the server-only `codestra-moneybee-connectors` package from the exact reviewed SDK repository commit:

```text
fd9a5c3fd49534a7f7492a452f53815c386687b9
```

That commit contains the MoneyBee connector package merged by SDK repository PR #71. It must not be replaced with `main`, `development`, a tag, or another moving reference during release preparation.

## Authority boundary

- MoneyBee remains the authoritative lending system.
- Codestra Middleware remains the integration and command control plane.
- Odoo remains a CRM projection.
- The SDK is server-only and is never bundled into a browser application.
- SDK installation does not activate a command, provider, live write, Odoo write, message, lender submission, payment, payout, or funding action.

## Activation contract

Initial repository and staging templates keep:

```text
CODESTRA_SDK_ENABLED=false
CODESTRA_SDK_CAPABILITIES_CSV=
MIDDLEWARE_PROVIDER=disabled
LIVE_WRITES=false
ODOO_WRITE=false
```

Before an environment may set `CODESTRA_SDK_ENABLED=true`, it must provide all of the following outside Git:

- `MIDDLEWARE_PROVIDER=codestra`;
- canonical HTTPS `CODESTRA_MIDDLEWARE_BASE_URL`;
- Codestra OAuth token URL, client ID, and client secret;
- nonempty `CODESTRA_SDK_CAPABILITIES_CSV` containing only approved capabilities;
- immutable `SOURCE_SHA` release provenance;
- approved network path and TLS validation;
- operation read-back and reconciliation evidence;
- separate authorization for any downstream live write.

The process fails closed in staging/production when the SDK is enabled without those prerequisites.

## Mutation and reconciliation behavior

`MoneyBeeCodestraCommands.submit_crm_projection()` sends one governed command through the SDK. The request carries tenant, principal, request, correlation, operation, idempotency, provider, and release context.

The client does not blindly retry an ambiguous mutation. A timeout or transport ambiguity becomes an unknown-outcome error. Operators or a durable worker must call `read_operation()` with the same operation ID before deciding whether another command is safe.

## Container boundary

Git is installed only where the immutable SDK source is resolved during the image build. The release runtime stage does not contain the build checkout or source credentials. Both Dockerfiles preserve application-owned proxy handling through `--no-proxy-headers`.

## Required release evidence

- exact SDK commit resolves and builds;
- backend unit and integration tests pass;
- API, worker, and migration images build as the unprivileged `moneybee` user;
- HIGH/CRITICAL vulnerability policy passes;
- SBOM/provenance records include the connector package;
- staging uses disabled capabilities first;
- command read-back and ambiguous-outcome reconciliation pass before any live activation.
