# MoneyBee system review — architecture, code, API, security

Mission: full-system review across `moneybee-backend` and `moneybee-frontend-`
to identify the concrete gaps between the current codebase and a "top tier"
production fintech system. This is an assessment only; it makes no code
changes and grants no deployment authority.

Companion document: `moneybee-frontend-/docs/codex/SYSTEM_REVIEW_2026-08-28.md`
(frontend-specific findings + the same cross-cutting section, kept in sync).

Method: direct reading of `app/`, `migrations/`, `tests/`, `docs/`, `deploy/`,
`.github/workflows/`, and `openapi.json`, cross-checked against this repo's
own `docs/codex/MB_RELEASE_READINESS_PACKET_20260827.md` so this review adds
to that self-assessment rather than repeating it.

## Overall assessment

This backend is meaningfully more mature than a typical "review my code"
target: async FastAPI + SQLAlchemy 2.0, a real tenant/identity model, a
transactional-outbox worker, fail-closed production config validation, and a
CI pipeline that pins actions by SHA, scans for private keys, round-trips
migrations, and enforces digest-only deploys. The gaps below are the
specific things standing between "solid" and "top tier" — not a rewrite.

## 1. Architecture

- **`app/routers.py` is a 2,211-line, 79-route monolith** — every
  application/matching/offer/complaint/lender-legacy endpoint lives in one
  file, while every other domain has since been split into its own module
  (`financial_routes.py`, `integration_routes.py`, `public_intake_routes.py`,
  `portal/{account,admin,borrower,lender,webhooks}.py`). This is the single
  biggest structural inconsistency in the codebase: two different
  organizing principles coexist, and the biggest, oldest domain is stuck on
  the one that doesn't scale. **High** — split `routers.py` into
  `applications_routes.py`, `matching_routes.py`, `conditions_routes.py`,
  `complaints_routes.py` (or fold the still-relevant pieces into
  `portal/`), mirroring the pattern already proven elsewhere in this repo.
- **Duplicated model/schema module names at different levels**
  (`app/models.py`, `app/financial_models.py`, `app/identity_models.py`,
  `app/integration_models.py`, `app/public_intake_models.py`, and a second
  `app/portal/models.py`) make "where does X live" non-obvious and invite
  circular imports (`main.py` already has to import four separate model
  modules by hand for side effects — `app/main.py:11-13`). **Medium** —
  either consolidate under `app/models/<domain>.py` as a real package, or
  document the split explicitly in a top-of-file docstring per module.
- **Provider adapter pattern is genuinely good**: `app/integrations/base.py`
  defines `Protocol`s per capability (bank, CRM, KYB, credit, lender,
  e-sign, email, SMS, object storage), `app/integrations/http.py` centralizes
  retry/backoff/timeout policy, and `app/integrations/registry.py` selects
  the configured implementation. This is the shape other parts of the
  codebase (`routers.py`) should be judged against, not the exception.
- **Worker uses a transactional outbox** (`app/worker.py`: `OutboxEvent`,
  `SELECT ... FOR UPDATE SKIP LOCKED`, lease expiry, `ENABLE_EXTERNAL_DELIVERY`
  runtime gate) — this is the correct pattern for reliable at-least-once
  delivery to external systems and is worth keeping as-is.
- **`redis_url` is configured (`app/config.py:14`) but never consumed** —
  no file under `app/` imports a redis client. Either it's dead
  configuration or it's used only by infra pieces not in this repo; either
  way it's misleading as-is. **Low** — remove it or wire it to something
  (rate limiting, see §4, would be a natural consumer).

## 2. Code quality

- **No application-level logging anywhere.** `grep -rn "logging\.\|logger =
  \|structlog" app/` returns nothing. Errors, provider failures, and
  timing are visible only through whatever uvicorn's default access log
  captures and through the DB-backed `AuditEvent`/`admin/audit-events`
  trail. The audit trail is the right mechanism for compliance-grade
  business events, but it's not a substitute for operational logs — right
  now there is no way to see a stack trace for a 500, no request-scoped
  structured logging keyed to the `X-Request-ID` the middleware already
  generates (`app/main.py:67-74`), and no hook for a log aggregator or
  APM/tracing tool. **High** for a production fintech system — this is the
  most impactful single gap for operability.
- **Domain logic is reasonably well isolated**: `app/domain_logic.py` and
  `app/notification_policy.py` read as pure-ish rule evaluators rather than
  HTTP handlers with business logic inlined, which keeps them unit-testable
  (and they are — see `tests/test_domain_logic.py`).
- **Money is handled correctly**: `Decimal` end-to-end, `Numeric(20, 2)` at
  the DB layer (`app/financial_models.py:155,223`), Pydantic `Decimal`
  fields with `max_digits`/`decimal_places` constraints
  (`app/financial_schemas.py:80`). No float-for-currency anti-pattern found.
- **Pydantic schemas are strict**: `ConfigDict(extra="forbid")` on request
  models rejects unexpected fields instead of silently dropping them —
  correct default for a financial API surface.
- No `TODO`/`FIXME`/`HACK` markers, no bare `except:`, no stray `print()`
  statements found in `app/` — good hygiene discipline, worth preserving as
  a lint rule if not already enforced (ruff is already wired into CI).

## 3. API design

- **Consistent versioning, but v1 is a silent full alias of v2.**
  `app/main.py:55-64` mounts every router at both `/api/v2` and `/api/v1`
  (the latter `include_in_schema=False`). There's no code-level signal for
  what "v1" means, when it can be removed, or whether it's actually behind
  v2 in behavior — it's the identical router object. If v1 is a
  deprecated-but-still-served compatibility alias, say so with a
  deprecation header and a sunset date; if it's dead, remove it. **Medium.**
- **Contract testing is real, not aspirational**: `scripts/verify_openapi_contract.py`
  runs in CI against the checked-in `openapi.json`, and `docs/openapi/*.json`
  manifests scope specific surfaces (account lifecycle, admin workspace,
  lender/frontend compat, provider webhook aliases, public intake) for
  targeted contract checks. This is a stronger API-contract discipline than
  most teams have.
- **Errors use RFC 7807** (`application/problem+json`) for validation
  failures (`app/main.py:77-94`) and a consistent `{code, message}` shape
  for auth/identity errors (`app/auth.py:78-84`, `app/identity.py`). Good —
  but the two shapes are different from each other (`type/title/status/...`
  vs `code/message`). **Low-Medium** — worth converging on one envelope
  (RFC 7807 with `code` folded into `type`/a custom extension member) so
  every client has exactly one error shape to parse.
- **Webhook security is solid**: `app/portal/webhooks.py` verifies
  `X-MoneyBee-Signature` with HMAC-SHA256 and `hmac.compare_digest`
  (constant-time), includes a timestamp-tolerance check, and there's a
  documented, enumerable provider webhook allowlist
  (`provider_webhook_allowlist_csv`) plus per-provider secrets
  (`provider_webhook_secrets_json`) rather than one shared secret.
- **No rate limiting or throttling anywhere** (`grep -rln "rate.limit\|throttl\|slowapi\|limiter" app/`
  is empty). This matters specifically for: `public_intake_routes.py`
  (unauthenticated by design — a lead-capture/public form surface),
  `app/portal/webhooks.py` inbound webhook endpoints, and login-adjacent
  flows. Signature verification stops forged webhooks but not floods; lack
  of throttling on public intake invites scraping/spam/credential-stuffing
  adjacent abuse. **High** — add per-IP/per-key rate limiting at minimum on
  public and webhook endpoints (edge-level via Caddy, or app-level via a
  small ASGI middleware) before this is internet-facing at scale.

## 4. Security

- **JWT verification is done correctly**, which is the part most APIs get
  wrong: `app/auth.py:99-126` requires a `kid`, restricts `alg` to an
  explicit allowlist (rejecting `alg: none` and algorithm-confusion
  attacks), verifies against a cached JWKS client, and requires
  `iss/sub/aud/exp/iat/nbf` claims to be present. Audience and issuer are
  both checked.
- **Tenant isolation is enforced server-side, not just via routing**:
  `app/identity.py` resolves `ExternalIdentity → User → OrganizationMembership
  → Role/Permission` per request and requires an explicit `X-Organization-ID`
  selection when a user belongs to more than one org; a requested org the
  user doesn't belong to is a `403 TENANT_ACCESS_DENIED`, not a filtered
  query. `app/config.py`'s `secure_environment` validator additionally
  **forbids overlapping OIDC client IDs between the borrower, lender, and
  admin portals** — a real, structural guarantee that one portal's tokens
  can't be replayed against another portal's endpoints, checked at process
  startup rather than left to code review.
- **Production config is fail-closed by construction**: the same validator
  refuses to start in `staging`/`production` if `local_auth_bypass` or
  `auto_create_schema` is still on, if `local_identity_enforcement` is off,
  if the issuer isn't the canonical `auth.codestra.co` host, if algorithms
  aren't `RS256`-only, or if any *enabled* provider (Plaid, Codestra
  middleware, Odoo, Middesk, Experian, SendGrid, Twilio, S3) is missing a
  required credential. This is exactly the right shape for preventing
  "it worked because a dev flag was still on" incidents.
- **Field-level encryption has no key rotation story**:
  `app/encryption.py` uses a single static Fernet key
  (`FIELD_ENCRYPTION_KEY`) with no key ID/versioning, so rotating the key
  requires decrypting and re-encrypting every stored secret atomically
  rather than rotating incrementally. Fernet itself is fine (AES-128-CBC +
  HMAC, authenticated); the gap is operational. **Medium** — at minimum,
  prefix ciphertext with a key version and keep the last key available for
  decrypt-only during rotation; longer term, consider envelope encryption
  via a KMS so the data-encryption key itself can rotate without touching
  ciphertext.
- **`/health/ready` only checks Postgres** (`app/main.py:102-112`) — it
  will report `ready` even if a configured provider or Redis (if it's ever
  wired up, see §1) is unreachable. Low blast radius today since nothing
  else depends on it, but worth widening before it's used as a real
  orchestrator health gate.
- No secrets found committed in `.env.example`/`.env.production.example`
  (both are placeholder-only) and `scripts/check_no_private_keys.py` runs
  in CI as a dedicated gate — good.

## 5. Testing

- 20 test files under `tests/`, with dedicated boundary tests for the
  things that actually matter in a multi-tenant portal system:
  `test_identity_tenancy_postgres.py`, `test_portal_token_boundaries.py`,
  `test_portal_client_boundaries.py`. This shows the team is testing
  *isolation*, not just happy paths — the highest-value place to spend test
  effort in this architecture.
- CI runs the full suite against real Postgres (not just SQLite), and
  separately exercises an `alembic downgrade` + `upgrade` round trip on
  every PR touching migrations — catches non-reversible migrations before
  merge, which most teams skip.

## Top recommendations, in priority order

1. **Add structured, request-scoped logging** (tie to the existing
   `X-Request-ID`), even a minimal `structlog`/stdlib JSON formatter to
   stdout — this is the biggest operability gap and the cheapest to close.
2. **Split `app/routers.py`** into domain modules matching the pattern
   already used by `financial_routes.py`/`portal/*` — highest-impact
   maintainability fix, no behavior change required.
3. **Add rate limiting** on public-intake and webhook endpoints at minimum
   (edge or app-level) before treating this as internet-facing at scale.
4. **Resolve the `/api/v1` alias**: either give it real deprecation
   semantics (header + sunset date) or delete it.
5. **Version the field-encryption key** so rotation doesn't require a
   flag-day re-encryption of every secret.
6. **Converge on one error envelope shape** across validation errors and
   auth/identity errors.
7. **Consolidate the model/schema module layout** so "where does this type
   live" has one obvious answer as the domain count grows.
8. **Widen `/health/ready`** to reflect the dependencies actually in play
   once any are added beyond Postgres.

None of these are blockers to what's already been shipped — they're the
specific list to work through to move this from "solid, well-governed
backend" to "top tier."
