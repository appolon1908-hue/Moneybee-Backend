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
- [x] **Field-encryption key versioning** — pass: `8e8aad2`. Done now that
      there's a real reason to (this pass's other work started actually
      persisting encrypted secrets — see the 1099 TIN item below).
      `FIELD_ENCRYPTION_KEYS_JSON` (a `{"<version>": "<fernet key>"}` map)
      + `FIELD_ENCRYPTION_ACTIVE_KEY_VERSION`; ciphertext is prefixed with
      its key version so decrypt always resolves the right key regardless
      of which version encrypted it — rotating no longer requires a
      flag-day re-encryption of every stored secret.
- [x] **Converge the two error-response shapes** onto one RFC 7807
      envelope — pass: `a4c9575`. The 22-assertion blast radius noted
      below had grown to 16 call sites across 9 files by the time this
      landed (some of the original 22 had since been superseded); all
      updated. One handler (`app/main.py`'s `http_exception_problem`)
      now normalizes every `HTTPException` regardless of how it was
      raised — required zero frontend changes since
      `packages/api-client/src/core.ts`'s error parsing already read
      `problem.code`/`problem.context` defensively, ahead of this
      landing.
- [x] **`/health/ready` widened** — pass: `2ed3c14`. Now also compares the
      database's `alembic_version` against the code's expected head via
      Alembic's `ScriptDirectory` (skipped when `auto_create_schema` is
      on, matching the same dev-only switch the startup validator treats
      specially) — catches "new code shipped, migration never ran," a
      real deploy failure mode plain DB-connectivity checking can't see.

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
- [x] **Contracts, funding, commission, renewal engines — all 4 steps
      complete.** Full draft spec at
      `docs/codex/CONTRACTS_FUNDING_COMMISSION_RENEWAL_SPEC_DRAFT.md`,
      reviewed and confirmed (commission is deal-negotiated and splittable
      across brokers; other lower-stakes questions defaulted and flagged
      there). Built in the spec's stated dependency order, each step
      tested against the real HTTP API, not mocked:
  - [x] **1. Funding state machine** — pass: `946491d`. Full six-stage
        lifecycle (`CONDITIONS_PENDING → CONDITIONS_SATISFIED →
        CONTRACT_SIGNED → APPROVED_FOR_FUNDING → FUNDS_SENT → FUNDED`,
        `DECLINED`/`CANCELLED` from any non-terminal state), four
        idempotent operator endpoints, Commission created at `confirm`
        with an operator-entered rate. Also fixed a real gap found while
        building this: the automatic `CONDITIONS_PENDING →
        CONDITIONS_SATISFIED` transition (pass: `4765c5c`) — without it
        funding could never organically leave `CONDITIONS_PENDING`.
        `approve`'s `CONTRACT_SIGNED` prerequisite is now reachable
        end-to-end since step 2 landed.
  - [x] **2. Contract / e-sign engine** — pass: `825628f`. `Contract`
        created (`DRAFT`) synchronously the moment funding reaches
        `CONDITIONS_SATISFIED`; `app/worker.py`'s
        `send_pending_contract_envelope()` sends it via the existing
        `esign_adapter()`/`DocuSignAdapter` (gated behind `ESIGN_LIVE_SEND`,
        the exact flag name from the readiness packet); its
        `process_pending_docusign_event()` consumes inbound
        `IntegrationInboxMessage` rows and, on a signed envelope, advances
        the linked `Funding` to `CONTRACT_SIGNED` — closing the loop back
        into step 1. DocuSign Connect payload field names are a flagged
        best-effort guess (never configured against a real account) —
        verify before going live.
  - [x] **3. Commission engine (receipts/splits)** — pass: `1efa659`.
        `POST /admin/commissions/{id}/receipts` (incremental running total,
        status flips to `PARTIALLY_RECEIVED`/`RECEIVED` against the *net*
        expected amount including adjustments) and
        `POST /admin/commissions/{id}/splits` (capped so splits can never
        exceed net expected). Verified by driving the entire real chain —
        steps 1+2+3 together — through the actual HTTP API for the first
        time, no DB-injection shortcuts except the inbound DocuSign
        payload itself.
  - [x] **4. Renewal engine** — pass: `532a5e1`.
        `evaluate_renewal_eligibility()` scans `FUNDED` fundings older
        than `RENEWAL_ELIGIBILITY_DAYS` (90, a flagged default per the
        spec's resolved open question 2) and creates one
        `RenewalOpportunity` per funding; `POST
        /admin/renewal-opportunities/{id}/status` moves the pipeline
        stage. Simplified the spec draft's `PENDING → OPPORTUNITY_CREATED
        → CONTACTED → …` to `PENDING → CONTACTED → CONVERTED/DECLINED/
        EXPIRED` — a row only ever gets created once already eligible, so
        "opportunity created" was a redundant state.

**Engine spec status: complete.** All four state machines exist, are
idempotent on every money-moving write, and compose correctly end-to-end
(verified in `tests/test_admin_commission_receipts_and_splits.py` by
driving offer acceptance → conditions → contract → signed webhook →
funding approval → commission through the real API in one test, no
shortcuts except the inbound DocuSign payload this environment has no
real account to receive one from). Two things flagged, not silently
assumed solid, for whoever takes this toward real DocuSign traffic:
the payload field-name mapping in `app/worker.py`'s
`process_pending_docusign_event()`, and the `RENEWAL_ELIGIBILITY_DAYS`/
commission-rate defaults recorded in the spec doc.
- [x] **Object storage + malware scanning** — pass: `7e79cab`. Audited
      first (per this doc's own note above about checking before assuming
      a gap): the S3-compatible client and the presigned-upload flow
      (`app/portal/borrower.py` + `app/integrations/storage.py`) were
      already real and complete, contradicting this line's original
      claim. What was actually missing: nothing consumed the
      `DocumentUploaded` outbox event, so every uploaded document was
      permanently stuck `QUARANTINED` forever. Added `ClamAVScanner`
      (talks clamd's INSTREAM wire protocol directly, tested against a
      real in-process TCP server) and `worker.scan_pending_document()`
      to actually close that loop — fails closed (stays `QUARANTINED`) on
      any error or when scanning isn't configured, matching
      `app/readiness.py`'s existing "not certified" launch gate, which
      is left in place on purpose: this makes the capability real and
      testable, it doesn't certify a live ClamAV deployment.
- [x] **Payment/payout rail (Stripe + PayPal)** — pass: `84c35b7`. The
      system review's single biggest flagged gap: no payment rail existed
      anywhere; `funding_funds_sent`/`confirm_funding` only ever recorded
      a `provider_reference` string typed in by hand. Added both adapters
      matching every other provider's frozen-capability pattern (real
      code, `PAYMENT_PROVIDER` stays `disabled`, `payments`/`payouts`
      stay `false` per `docs/codex/CAPABILITY_FREEZE.md`) plus inbound
      webhooks with each provider's own native signature verification.
      Deliberately **not** wired into the funding engine — whether
      MoneyBee originates transfers itself or stays a system of record
      while lenders wire funds is a business decision, documented as an
      open question in `docs/PROVIDER_ADAPTERS.md` rather than guessed at.
- [x] **Plaid webhook receiver** — pass: `9cf922a`. The system review
      flagged this as missing; it wasn't — `POST /webhooks/plaid` already
      existed in `app/banking_routes.py` with real signature verification,
      just grepped past during the review (only checked
      `app/portal/webhooks.py`). The real gap: it recorded every webhook
      but never consumed the `PlaidWebhookReceived` outbox event it wrote,
      so an `ITEM`/`ERROR` webhook — Plaid's "this bank connection needs
      re-auth" signal — went nowhere. Now updates the matching
      `BankConnection.status` inline (`REAUTH_REQUIRED` /
      `CONNECTED` on `LOGIN_REPAIRED`) rather than through the outbox,
      since it's a plain internal write with no external delivery/retry
      semantics to justify that pattern.
- [x] **Compliance: adverse-action notices, commercial-financing
      disclosures, 1099 commission tax records** — pass: `2ac9ac0`. The
      system review's compliance finding: a grep for "adverse action",
      "ECOA", "Reg B", "1099", or "license" across the whole backend
      returned zero matches anywhere. Added `app/compliance_models.py` /
      `app/compliance_service.py` (migration `20260901_0022`) covering all
      three:
      - Adverse-action notices generate automatically on a lender's
        `DECLINE` decision (`app/portal/lender.py`), covering Reg B Sec.
        1002.9(a)(2)'s required elements (creditor identity, principal
        reasons, the ECOA notice reproduced from 12 CFR Part 1002 Appendix
        C). Does **not** cover the >$1MM-revenue business-credit exception
        (Sec. 1002.9(a)(3)) or FCRA score-disclosure triggers — flagged
        explicitly in the generator's docstring, not silently assumed.
      - Commercial-financing disclosures generate automatically on offer
        creation (`app/marketplace_routes.py`), computing amount financed,
        finance charge, total repayment, and an APR (estimated from the
        finance charge for factor-rate offers) per the model California SB
        1235 follows. Does **not** select a state-specific
        template/layout/eligibility threshold — jurisdiction is recorded
        informationally pending real legal review of state variants.
      - 1099 commission tax records aggregate `CommissionSplit` amounts per
        recipient per tax year via a new admin-triggered generation
        endpoint, applying the federal $600 (IRC Sec. 6041) threshold.
        Idempotent — recomputes rather than accumulates on re-run.
        Recipient TINs are stored via the versioned field encryption from
        the Phase 1 key-rotation item and never returned in the clear.
        Does **not** file with the IRS; this produces the input data a real
        e-file integration (Track1099/Tax1099/IRS FIRE) would need, not the
        filing itself. Docstring documents the attribution caveat: there's
        no dedicated commission-receipt/disbursement-date table in this
        schema (`POST /admin/commissions/{id}/receipts` just increments
        `Commission.received_amount`), so `CommissionSplit.created_at` is
        used as a tax-year proxy rather than a true payment date.
      6 new admin endpoints, 6 new schemas, new additive OpenAPI manifest
      (`docs/openapi/compliance-records-manifest.json`). Tested end-to-end
      through the real API in `tests/test_adverse_action_notice.py`,
      `tests/test_commercial_financing_disclosure.py`, and
      `tests/test_commission_tax_records.py`.

Also fixed one live bug found auditing an unrelated file during the
payment-adapter pass: `app/integrations/registry.py`'s "bank" health
check still referenced the pre-rotation `settings.field_encryption_key`
attribute name, removed by the key-versioning item above — silently
short-circuited past in every test (nothing sets `plaid_client_id`
there) but would have thrown `AttributeError` the moment real Plaid
credentials were configured. Fixed alongside the payment adapters
(`84c35b7`).

**Note on branch history**: partway through this pass, a separate
automated process ("Codestra remediation") pushed real, substantial work
to this same branch — structured-observability scaffolding, a
production-launch-check script, an endpoint-catalog generator, and a rate
-limiting test suite — but left two pieces half-wired: `app/config.py` had
`public_rate_limit_per_minute`/`webhook_rate_limit_per_minute` declared
twice with different defaults (the second silently shadowed the first),
and the new rate-limit test suite imported a `reset_rate_limit_state()`
that didn't exist and referenced `rate_limit_enabled`/
`rate_limit_window_seconds` settings that were declared but never read.
Merged and finished both (pass: `444f476`) rather than reverting — see
that commit for detail.
- [ ] **Real provider adapters** promoted from scaffolded/generic-HTTP to
      fully tested per-provider implementations (Plaid, Experian, Middesk,
      Odoo) — confirm each against provider sandbox contracts, not just
      the internal `Protocol` shape.
- [x] **Bank-connection exchange/sync flow fixed against a real credential
      store.** Found broken while cross-checking an independent parallel
      "Codex" pass's certification report against this repo's actual state
      (it flagged "incompatible bank credential storage"): commit `283b789`
      ("fix(security): keep bank credentials outside MoneyBee") required
      adapters return an opaque `credential_reference`, but
      `PlaidAdapter.exchange_public_token` still returned Plaid's real
      `access_token`, and `PlaidAdapter.resolve_access_token` was an
      unconditional stub — the exchange/sync flow always 503'd, untested,
      regardless of provider configuration.
      Fixed by moving credential storage out of the per-provider adapter
      (which now only ever talks to Plaid, matching what it actually is)
      and into `app/banking.py`'s orchestration, behind a new
      `CredentialStore` Protocol (`app/integrations/base.py`) implemented
      by self-hosted HashiCorp Vault's KV v2 API
      (`app/integrations/vault.py`, `BANK_CREDENTIAL_STORE_PROVIDER=vault`).
      Chose Vault over a managed-cloud secrets service specifically because
      this project deploys to one self-hosted Docker Compose host (see
      `deploy/`), not any cloud vendor — matching the actual target rather
      than introducing a new one. `app/banking.py`'s `exchange_public_token`
      now calls `credential_store().store(access_token)` and persists only
      the reference; `sync_bank` resolves it back per-request and never
      caches the raw token. Production's fail-closed validator
      (`app/config.py`) now requires a live credential store before Plaid
      can be enabled at all — the whole point being closed, not just
      documented. Compose infrastructure added end to end: `deploy/
      compose.data.yml`'s optional, profile-gated (`bank-credential-store`)
      `vault` service (hardened the same way postgres/redis are — cap_drop
      ALL, read-only root, no published port, never on `moneybee_edge`)
      plus `deploy/vault-config.hcl` (file storage, TLS disabled — trusts
      the same docker-internal network isolation postgres/redis already
      do); local dev's `docker-compose.yml` gets the equivalent in Vault's
      dev-mode (auto-unsealed, fixed root token) for actually exercising
      the real code path. `ops/render-compose-env.py`/`release.lock.json`/
      `runtime-paths.lock.json` all extended, keeping `vault` optional
      (unlike `api`/`worker`/`migrate`) since most deployments will never
      turn this capability on. `ops/verify-runtime-env.py`'s fail-closed
      staging gate now also checks `BANK_CREDENTIAL_STORE_PROVIDER`.
      **Still explicitly not done**: actually initializing and unsealing a
      real Vault instance is a one-time operator action this repo cannot
      perform (see `deploy/README.md`) — `bank.credential_store_certified`
      stays `false` in `docs/codex/CAPABILITY_FREEZE.md` until that
      happens. Also found and fixed in passing: `docs/codex/
      CAPABILITY_FREEZE.md` never listed `bank.live_connection` at all
      despite it being a real, checked capability flag since before this
      pass, and `deploy/release.lock.json`'s `capabilities` map was
      missing `payments`/`payouts`/`malware_scan_certified` from earlier
      in this mission — both synced now.
      Tests: `tests/test_banking_credential_reference_contract.py` (6
      tests) — proves the raw token is never persisted, `sync_bank`
      resolves it correctly, the flow still fails closed with no
      credential store configured (the default), and `VaultCredentialStore`
      handles Vault's KV v2 request/response shape correctly.
- [x] **RBAC permission-enforcement coverage** — pass: `tests/
      test_rbac_permission_enforcement.py`. Every other test in this suite
      runs under `LOCAL_AUTH_BYPASS`, which always resolves to a
      MONEYBEE_ADMIN principal holding the `"*"` wildcard
      (`_local_bypass_principal`) — so nothing else ever exercised a
      denial for a real, restricted role, only the one always-succeeds
      path. New file directly covers all three permission-enforcement
      mechanisms in use across the app: `require_permission()` (the
      single-permission FastAPI dependency), `require_any_permission()`
      (the any-of inline check in `app/portal/lender.py`), and the
      hand-rolled "own resource" checks in `app/applications_routes.py`.
      65 tests: every permission string any role in `LEGACY_ROLE_PERMISSIONS`
      actually grants is proven both to be granted with that exact
      permission and denied without it; every role is proven to be denied
      at least one permission outside its declared set (e.g. BORROWER
      denied `application.read`, MONEYBEE_SALES denied
      `underwriting.review`); and the six new admin compliance endpoints
      from this mission are exercised end-to-end via `TestClient` with a
      real restricted `Principal` injected through
      `app.dependency_overrides[current_principal]` — not the bypass
      principal — proving `application.read`/`application.edit`/
      `commission.receipt.record` are actually wired to those routes, not
      just declared. Confirmed non-vacuous: every denial assertion is a
      real `HTTPException`/403 raised by production code in the same run
      as the matching grant assertion.
      Deliberately out of scope for this pass: end-to-end RBAC tests for
      the dozens of pre-existing endpoints beyond the six new ones (the
      permission-dependency-level coverage above already proves the
      shared enforcement mechanism is correct for every declared
      permission; wiring is checked per-route only for what this mission
      added) — a good next slice if this needs to go further.
- [ ] Remaining target DB tables per the spec's "Database target" section
      not yet present — reconcile against `migrations/versions/` and add
      what's missing (compliance's adverse-action/disclosure/1099 tables
      landed this pass — see the compliance item above; still open:
      communications: templates/preferences; integrations: reconciliation).
- [x] **Code-review hardening pass on the funding/contract/commission/renewal
      engine** — 4 findings, all closed, pass: `615a7de`:
      - `funding_funds_sent` / `confirm_funding`: a second call with a
        *fresh* idempotency key after the funding had already reached
        FUNDS_SENT/FUNDED fell through `transition_funding`'s intentional
        "already at target status" no-op and silently re-ran side effects
        (overwriting `provider_reference`/`funds_sent_at`, or inserting a
        duplicate `Commission` row). Both endpoints now `409
        FUNDING_ALREADY_FUNDS_SENT` / `FUNDING_ALREADY_FUNDED` before any
        mutation when already at the target status.
      - `rate_limit._client_key()` trusted `X-Forwarded-For`
        unconditionally — any client could bypass the per-IP limiter by
        sending a fresh spoofed header per request. Added
        `settings.trust_forwarded_for` (default `False`, fail-closed);
        the header is only honored once an operator explicitly enables it
        for a deployment that sits behind a real, header-overwriting
        reverse proxy.
      - `evaluate_renewal_eligibility`: replaced the per-funding
        existing-opportunity query (N+1) with one batched `IN` query.
- [x] **Code review of the compliance pass** (adverse-action/disclosure/1099,
      Stripe+PayPal, ClamAV) — 1 confirmed finding, closed, pass: `7a9827b`:
      `generate_commercial_financing_disclosure`'s `disclosure_text`
      f-string had adjacent literals concatenated into one string *before*
      a trailing `if estimated_apr is not None else ...` applied, so
      whenever `estimated_apr` was `None` the ternary picked between "the
      whole four-line block" and "just the APR-unavailable line" instead of
      only the APR line — silently dropping amount financed/finance
      charge/total repayment from a state-mandated cost disclosure. Not
      reachable through the API today (`OfferInput` keeps amount/term above
      zero, the only way `estimated_apr` goes `None`), but wrong in the
      service function itself. Fixed by computing the APR line separately;
      added a direct unit test against the service function that reproduces
      the exact scenario (verified it fails pre-fix, passes post-fix).
- [x] **Fixed a real vulnerability found via a parallel automated pass**:
      the commercial-financing disclosure acknowledgment endpoint took
      `acknowledged_by` straight from the request body, so any caller with
      `application.edit` could attribute the acknowledgment to whoever they
      typed rather than who actually acknowledged it — a real integrity gap
      in a compliance record meant to prove a specific person accepted the
      disclosure. A CI job on this branch had the exact fix scripted
      (`authenticated-acknowledgment-hardening` in `secure-ci.yml`, added by
      a parallel process) but only fires on the next PR sync; applied it
      directly instead of leaving the gap live. `acknowledged_by` is now
      derived from the authenticated principal; the now-pointless
      `CommercialFinancingAcknowledgeInput` schema is gone. `docs/security/
      COMPLIANCE_RECORDS_SECURITY_CONTRACT.md` (also landed by the parallel
      process) documents this as a standing rule: acknowledgment/attribution
      always comes from the authenticated principal, never a client value.
- [x] **Docker/deploy readiness pass** — pass: `61c6a81`. Docker Hub image
      pulls are blocked by this environment's own egress policy (confirmed
      via the agent proxy's relay-failure log — a 403 policy denial on
      `production.cloudfront.docker.com`, the CDN Docker Hub blob fetches
      redirect through; tried docker.io directly and the public.ecr.aws
      mirror, both denied identically), so this pass could not exercise an
      actual `docker build` end-to-end. Everything checkable without a
      registry pull was checked instead — all 4 Compose files validated
      with `docker compose config` against both `.env.example` and CI's
      exact synthetic fixtures, every `ops/*.py` script's CI invocation
      reproduced locally — and it found real gaps:
      - `ops/verify-runtime-env.py`'s fail-closed staging gate never
        checked `PAYMENT_PROVIDER` or `MALWARE_SCAN_PROVIDER` — both
        capabilities added earlier this pass could have been set live in a
        staging env file and the gate would have said nothing. Added both
        to `REQUIRED_EXACT`; verified locally it now rejects either live,
        same as every other provider.
      - `.env.example` / `.env.production.example` never got
        `MALWARE_SCAN_PROVIDER`/`CLAMAV_HOST`/`CLAMAV_PORT`/
        `CLAMAV_TIMEOUT_SECONDS` when the malware-scan capability landed —
        `app/config.py` had the settings, nothing documented them.
      - `docs/codex/CAPABILITY_FREEZE.md` was missing a frozen-capability
        line for malware scanning — added
        `documents.malware_scan_certified = false`.
      - `deploy/README.md` documented a single `docker-compose.production.yml`
        with a `build` step that doesn't exist and that CI's own
        `deployment-policy` job actively forbids (`build:` keys are banned
        in `deploy/compose.*.yml`). Rewritten to describe the real
        three-Compose-file model and the actual
        `validate → verify-runtime-env → render-compose-env → up` sequence.
      - Local dev `docker-compose.yml` had no way to exercise the real
        `app/integrations/malware_scan.py` path at all. Added an opt-in
        `clamav` service (`--profile malware-scan`), off by default.
      - No `.dockerignore` existed. Both Dockerfiles already `COPY` an
        explicit allowlist rather than `COPY . .`, so this isn't closing a
        live secret-leak path, but it shrinks build context and is
        defense-in-depth if that ever changes.

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
