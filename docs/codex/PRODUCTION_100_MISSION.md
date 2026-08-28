# MoneyBee → 100% production mission

Mission: `MB-100-PERCENT-PRODUCTION`. Single tracked plan, spanning both
repos, to go from "reviewed and well-governed" (see
`docs/codex/SYSTEM_REVIEW_2026-08-28.md`) to spec-complete and
production-ready. This is a living checklist — it gets updated and
checked off pass by pass, each pass committed and pushed with an
explanation of exactly what changed.

Companion: `moneybee-frontend-/docs/codex/PRODUCTION_100_MISSION.md`
(frontend-side checklist; phases 0 and 5 are shared and kept identical).

## What "100% / green light" means here, precisely

Checked against three sources of truth already in this repo, not invented:
`docs/MONEYBEE_V3_BACKEND_SPEC.md` (target API/DB surface + its own
"Current implementation status" gap list), `docs/codex/SYSTEM_REVIEW_2026-08-28.md`
(hardening gaps found by direct code review), and
`docs/codex/MB_RELEASE_READINESS_PACKET_20260827.md` (this org's own
deploy-authorization gate). "100%" = every checkbox below is checked, CI is
green on every required job, and the two PRs (backend #33, frontend #24)
are mergeable with no open conversations.

**Explicit scope boundary**: this mission gets the system to
*deploy-ready* — code complete, tests green, capability-freeze flags
correctly OFF. It does **not** perform the actual production cutover.
Per this repo's own readiness packet, that requires a named human
operator, a real target host, immutable image digests, verified
backup/restore evidence, and a literal authorization statement — none of
which exist yet and none of which I can create from here (no production
credentials, no access to real Plaid/Experian/Middesk/Odoo/SendGrid/Twilio
accounts). Phase 5 below spells out exactly what a human operator still
has to do; everything before it is mine to execute.

## Phase 0 — Governance (shared, no code)

- [x] System review completed and pushed (`SYSTEM_REVIEW_2026-08-28.md`)
- [x] PR #33 open on `claude/system-review-architecture-8vo66p` (backend)
- [x] PR #24 open on `claude/system-review-architecture-8vo66p` (frontend)
- [ ] Every commit in this mission keeps the two PRs' required checks green
      before moving to the next pass (never push on a red local run)
- [ ] This file's checkboxes match reality after every pass (updated in the
      same commit as the code, not after)

## Phase 1 — Production hardening (from the system review, code-only, low risk)

**Status: closed.** 3 of 6 items landed as code; 3 were re-scoped after
checking their actual premise/blast radius rather than done speculatively
(see notes on each below) — 2 had nothing left to do until later Phase 2
work exists, 1 (error-envelope convergence) is real but large enough to
need its own pass.

- [x] Structured, request-scoped logging (JSON to stdout, keyed to the
      existing `X-Request-ID`), plus a catch-all exception handler so an
      unhandled error is logged with a stack trace server-side and returns
      a clean RFC 7807 500 to the client instead of leaking internals
      — `app/logging_config.py`, `app/main.py` (pass: `af8486c`)
- [x] Rate limiting on unauthenticated surfaces (`public_intake_routes.py`,
      `portal/webhooks.py`) — in-process fixed-window limiter for now,
      documented in-code as a stopgap pending edge/Redis-backed limiting
      at real scale — `app/rate_limit.py` (pass: `af8486c`)
- [x] Split `app/routers.py` (2,211 lines / 83 functions) into domain
      modules matching the pattern already used by `financial_routes.py` /
      `portal/*.py` — `applications_routes.py`, `marketplace_routes.py`,
      `admin_routes.py`, `borrower_legacy_routes.py`, `banking_routes.py`
      (pass: `9bff2a7`). Verified as a true no-op by diffing the live
      `app.openapi()` output before/after as parsed JSON (not text): paths,
      operations, schemas, and security schemes all identical.
- [x] `/api/v1` given real deprecation semantics (`Deprecation: true`,
      `Sunset: <date>`, and a `Link: <v2-equivalent>; rel="successor-version"`
      response header, configurable via `api_v1_sunset_date`) instead of
      being a silent, undated full alias of v2 (pass: backend)
- [ ] ~~Field-encryption key versioning~~ — **corrected, not done as
      planned**: checked every caller of `app/encryption.py` before
      touching it and found there are none anywhere in `app/` or `tests/`.
      `resolve_access_token()` in `app/integrations/plaid.py` deliberately
      raises `ProviderError("plaid", "An external credential store must
      resolve bank credential references")` — the DB only ever stores an
      opaque `credential_reference` (`app/models.py:793`), never a raw
      provider secret. `encrypt_secret`/`decrypt_secret` are unwired
      scaffolding for a credential store that doesn't exist yet, not an
      active gap with nothing to rotate. Re-scoped under Phase 2's "real
      provider adapters" item below — versioning is worth building at the
      same time credentials are first actually persisted, not before.
- [ ] Converge the two error-response shapes (RFC 7807 validation errors vs.
      `{code, message}` auth/identity errors) on one envelope — **checked
      the blast radius before starting**: 22 assertions across 12 test
      files depend on the current `{code, message}` shape via
      `HTTPException.detail`. Real fix, but a dedicated pass on its own,
      not a quick Phase 1 item — deferred, not skipped.
- [ ] ~~`/health/ready` widened~~ — **corrected, not done as planned**:
      there is currently nothing beyond Postgres to widen it to. Redis is
      configured (`redis_url`) but unused anywhere in `app/`, and every
      provider adapter is still a stub (see above). Re-scoped: widen this
      alongside whichever Phase 2 item first gives the app a second real
      runtime dependency, not before.

## Phase 2 — Backend spec completion (per `docs/MONEYBEE_V3_BACKEND_SPEC.md` §"Not yet complete")

This is the big one — the spec itself lists what's outstanding. Tracked
here in the order that unblocks the most downstream work first:

- [x] **Idempotency persistence** — **corrected: the spec doc's "not yet
      complete" note here is stale.** Audited before doing any work and
      found `IdempotencyRecord`/`idempotency_keys` already fully wired
      (actor+route+key, request-hash conflict detection, response replay)
      into offer acceptance, lender submission decisions, public
      prequalifications, public intake forms, and account bootstrap. Only
      real gap found: `POST /admin/commissions/{id}/adjustments` (a real,
      already-shipped endpoint) had none — fixed, pass: `59b23b9`
      (deliberate breaking API change; a required header added to an
      endpoint with no known consumers yet). "Contract creation" and
      "funding confirmation" genuinely have no persistence yet because
      those endpoints don't exist at all — tracked as part of the
      contracts/e-sign and funding engines below, not a standalone gap.
- [x] **Conditions/offers state machine completion** — pass: `e53c4ce`.
      Conditions: audited, essentially complete (validated state machine
      already in `app/marketplace_routes.py`; 2 of 7 spec-named states
      unused but no functional gap, noted not fixed since there's nothing
      broken). Offers: real gap found and fixed — `prepayment_terms`,
      `personal_guarantee_required`, `collateral_description` didn't exist
      anywhere; added to the model/schema/migration.
- [ ] **Contracts / e-sign engine**: DocuSign adapter exists
      (`app/integrations/` has the provider settings) but the
      contract-creation → e-sign-send → signed-callback → funding-eligible
      state machine described in the spec's "Funding, commissions, and
      renewals" section is not yet built end-to-end.
- [ ] **Funding, commission, and renewal engines**: the full lifecycle
      (accepted offer → conditions → contract signed → approved for funding
      → funds sent → funded → commission expected/received) plus the
      renewal worker that evaluates funded accounts and creates renewal
      opportunities. This is the largest single piece of remaining domain
      logic.
- [ ] **Object storage + malware scanning** for document uploads (adapter
      interface exists in `app/integrations/base.py`; scanning step and
      real S3-compatible wiring do not).
- [ ] **Real provider adapters** promoted from scaffolded/generic-HTTP to
      fully tested per-provider implementations (Plaid, Experian, Middesk,
      Odoo) — confirm each against provider sandbox contracts, not just
      the internal `Protocol` shape.
- [ ] **Complete RBAC test coverage**: extend the existing tenancy/portal
      boundary tests (`test_identity_tenancy_postgres.py`,
      `test_portal_token_boundaries.py`, `test_portal_client_boundaries.py`)
      to cover every permission in `LEGACY_ROLE_PERMISSIONS`
      (`app/auth.py`) and every new endpoint added in this mission.
- [ ] Remaining target DB tables per the spec's "Database target" section
      not yet present — reconcile against `migrations/versions/` and add
      what's missing (compliance: versioned disclosures/acceptances,
      adverse actions; communications: templates/preferences; integrations:
      reconciliation).

## Phase 3 — See frontend companion doc for portal/dashboard completion

`apps/lender` is the furthest behind its target feature slices (spec wants
`underwriting`, `conditions`, `offers`, `programs`, `funded`, `reports`,
`settings`; only `dashboard`, `submissions`, and a combined workspace view
exist today). `apps/admin` is close to its target slice list but several
(`fraud`, `matching`, `commissions`, `compliance`, `complaints`,
`affiliates`, `audit`) need confirming as real views vs. planned. Backend
endpoints for a slice must land in Phase 2 before the frontend view for it
is meaningful — don't build a screen against an endpoint that doesn't
exist yet.

## Phase 4 — Test & CI green-light criteria

- [ ] `pytest -q` green locally and in CI after every pass
- [ ] `ruff check app tests migrations scripts` clean
- [ ] `alembic downgrade`/`upgrade` round-trip clean for every new migration
- [ ] `scripts/verify_openapi_contract.py` passes (checked-in `openapi.json`
      regenerated via `scripts/export_openapi.py` whenever routes change)
- [ ] Frontend `pnpm typecheck`, `pnpm test`, `pnpm contracts:check` all
      green (see frontend companion doc)
- [ ] Both PRs (#33, #24) show all required status checks green with no
      unresolved review threads

## Phase 5 — What a human operator does from here (not part of this mission)

Per `docs/codex/MB_RELEASE_READINESS_PACKET_20260827.md`, once Phases 1-4
are checked off and both PRs are merged:

1. Name the target host, maintenance window, and authorized executor.
2. Obtain real credentials for every enabled provider (Plaid, Experian,
   Middesk, Odoo, SendGrid, Twilio, DocuSign, S3-compatible storage) and
   load them server-side only — never in this repo, never in chat.
3. Build and publish digest-pinned images (api/worker/migrate + the four
   frontend containers); populate `deploy/release.lock.json` with real
   SHA-256 digests — no mutable tags.
4. Record a database backup and a successful restore drill into an
   isolated database before any migration runs against real data.
5. Run the dedicated migrate image once, verify the Alembic head matches
   the lock file, then start application images.
6. Flip the capability-freeze flags in the readiness packet from `false`
   to the intended live values **one at a time**, verifying each in
   staging before production.
7. Confirm CORS, OIDC issuer, and DNS all point at the real
   `moneybeeloan.com` / `auth.codestra.co` production values (staging
   examples currently reference `*-staging.moneybeeloan.com`).

I'll flag explicitly, every time a pass in this mission touches something
that changes what Phase 5 needs (a new required env var, a new provider
credential, a new migration to include in the lock file) — so this list
stays accurate rather than stale.

## Working method

Each pass: pick the next unchecked item(s) small enough to test in one
sitting → implement → run the real local checks (pytest/ruff/alembic or
pnpm typecheck/test/contracts) → commit → push to the existing PR branch →
report exactly what changed, what was verified, and what's next → check the
box → move to the next pass. No pass merges its own PR or touches
production.
