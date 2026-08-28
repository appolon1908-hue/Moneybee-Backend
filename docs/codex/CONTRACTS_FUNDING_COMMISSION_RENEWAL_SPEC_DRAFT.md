# Contracts, funding, commission, and renewal engines — draft spec

Status: **draft, not implemented.** This proposes concrete state machines,
endpoints, and fields for the two largest items in
`docs/codex/PRODUCTION_100_MISSION.md` Phase 2. It exists to be reacted to,
corrected, and approved before any code is written — the open questions at
the bottom are decisions I'm not making unilaterally.

Grounded entirely in what's already in this repo, not invented from a blank
page:

- `docs/MONEYBEE_V3_BACKEND_SPEC.md`'s target lifecycle: *accepted offer →
  pending/completed conditions → contract ready/signed → approved for
  funding → funds sent → funded → commission expected/received*, plus a
  renewal worker that evaluates funded accounts.
- Models that **already exist and already match this shape** (I checked —
  nothing here needs a new migration for the entities themselves):
  `Contract` (`app/models.py:489`), `Funding` (`:511`), `Commission`
  (`:540`), `RenewalOpportunity` (`:555`), `CommissionSplit` (`:727`),
  `CommissionAdjustment` (`:742`, now idempotent as of the last pass).
- What's actually missing, confirmed by grepping every write of these
  models: `Funding` rows are created (at offer acceptance,
  `app/applications_routes.py:307`) but **never transition past
  `CONDITIONS_PENDING`**, and `Contract`, `Commission`, and
  `RenewalOpportunity` are **never created anywhere**. Every read/list
  endpoint for them already exists (`app/admin_routes.py`); every write
  path does not.
- The notification vocabulary is already fully pre-declared and unused:
  `contract.sent.v1`, `contract.signed.v1`, `funding.confirmed.v1`,
  `renewal.eligible.v1` (`app/notification_policy.py`) — this spec routes
  through exactly those event names, not new ones.
- `app/integrations/providers.py`'s `DocuSignAdapter` and
  `app/integrations/base.py`'s `ESignAdapter` protocol
  (`send_envelope(contract_id, signer_email, signer_name)`) already exist
  as the integration point; `app/portal/webhooks.py:285`'s
  `docusign_webhook` already receives and durably stores inbound DocuSign
  events as `IntegrationEvent` rows — nothing yet reads and applies them.
- The state-machine *pattern* to reuse already exists and is proven:
  `app/services.py:15`'s `APPLICATION_TRANSITIONS` dict +
  `transition_application()` (`:490`) — validates `from → to` against an
  allowed-transitions map, raises `409 INVALID_..._TRANSITION` with the
  allowed set on rejection, bumps a version counter, writes a history row
  (`ApplicationStatusHistory`, `app/models.py:129`). Proposing the same
  shape for `Funding` and `Contract` below, not a new pattern.

## 1. Contract / e-sign engine

### Contract state machine

```
DRAFT → SENT → SIGNED
  ↓       ↓
VOIDED  DECLINED / EXPIRED
```

- `DRAFT`: created, not yet sent to the signer.
- `SENT`: envelope dispatched via the configured `ESignAdapter`
  (DocuSign today; `esign_provider` config already supports
  `disabled`/`docusign`). Sets `sent_at`, `external_envelope_id`.
- `SIGNED`: terminal happy path. Sets `signed_at`, `document_hash`.
- `DECLINED` / `EXPIRED`: terminal unhappy paths, reported by the provider
  webhook.
- `VOIDED`: an operator or the borrower cancels a `DRAFT`/`SENT` contract
  before signature (e.g. offer superseded).

### Trigger: when does a Contract get created?

Proposed: automatically, via the outbox, when `Funding.status` transitions
into `CONDITIONS_SATISFIED` (see funding state machine below) — mirroring
how `offer.accepted.v1` already fires an outbox event at
`app/applications_routes.py:314-330`. A worker consumer creates the
`Contract` row and calls `ESignAdapter.send_envelope(...)`, moving it
`DRAFT → SENT` in the same step (or `DRAFT` only, with `SENT` a separate
retryable worker step, if `send_envelope` should be allowed to fail and
retry independently of contract creation — this is one of the open
questions below).

### New/changed endpoints

- `GET /applications/{id}/contract` — read current contract (borrower +
  admin), mirroring `GET /applications/{id}/funding`'s existing shape.
- `POST /admin/contracts/{contract_id}/void` — operator-initiated `VOIDED`
  transition, permission-gated (new permission, e.g. `contract.void`),
  idempotent (`Idempotency-Key`, same pattern as
  `create_commission_adjustment`).
- **No manual "create contract" endpoint** — creation is automatic per the
  trigger above, matching how `Funding` creation is automatic today rather
  than a separate borrower/admin action.

### Applying inbound DocuSign events

`docusign_webhook` already lands events in `IntegrationEvent` with
`status="RECEIVED"` (`app/portal/webhooks.py:179,193`) — confirmed by
reading the actual write, not assumed. Proposing a new worker step —
`process_docusign_events()`, same shape as `app/worker.py`'s existing
outbox claim loop but consuming `IntegrationEvent` rows where
`provider="docusign"` and `status="RECEIVED"` — that maps the
provider's envelope-status payload to the `Contract` transition
(`completed` → `SIGNED`, `declined` → `DECLINED`, `voided` → `VOIDED`)
and then, on `SIGNED`, transitions the linked `Funding` to
`CONTRACT_SIGNED` (see below) and emits `contract.signed.v1`.

## 2. Funding state machine

Current: `Funding.status` defaults to `CONDITIONS_PENDING` at offer
acceptance and never changes. Proposed full sequence, matching the spec's
stated lifecycle exactly:

```
CONDITIONS_PENDING → CONDITIONS_SATISFIED → CONTRACT_SIGNED
  → APPROVED_FOR_FUNDING → FUNDS_SENT → FUNDED
```

with `DECLINED` / `CANCELLED` reachable from any non-terminal state.

- `CONDITIONS_PENDING → CONDITIONS_SATISFIED`: automatic, evaluated
  whenever a `Condition` reaches `SATISFIED` or `WAIVED` (existing
  transitions in `app/marketplace_routes.py`) — check whether every
  condition on the funding's application is now satisfied/waived, and if
  so transition. This is the one funding transition that's evaluated as a
  side effect of an existing action rather than a new endpoint.
- `CONDITIONS_SATISFIED → CONTRACT_SIGNED`: automatic, driven by the
  Contract engine above.
- `CONTRACT_SIGNED → APPROVED_FOR_FUNDING`: **operator action** —
  `POST /admin/fundings/{id}/approve`, permission-gated
  (`funding.approve`), idempotent. This is a deliberate human checkpoint,
  not automatic, matching the spec's "authoritative decisions require
  audit" framing for money-moving steps.
- `APPROVED_FOR_FUNDING → FUNDS_SENT`: **operator action** —
  `POST /admin/fundings/{id}/funds-sent`, sets `funds_sent_at` and
  `provider_reference` (e.g. a wire/ACH reference the operator enters).
- `FUNDS_SENT → FUNDED`: **operator action** —
  `POST /admin/fundings/{id}/confirm`, sets `funding_confirmed_at` and
  `funded_amount`. This is the spec's named "funding confirmation"
  idempotent command. Emits `funding.confirmed.v1`. Also the trigger for
  Commission creation (below).
- `DECLINED` / `CANCELLED`: **operator action**, any non-terminal state,
  with a required reason (audit trail).

All four operator actions above are the spec's "funding confirmation"
class of command and get the same idempotency treatment as
`create_commission_adjustment`.

## 3. Commission engine

### Creation trigger

Proposed: automatic, via outbox, when `Funding.status → FUNDED`. Creates
one `Commission` row (`status="EXPECTED"`) with `expected_amount`
computed from a rate (see open question 1) applied to `funded_amount`.

### Commission state machine

```
EXPECTED → PARTIALLY_RECEIVED → RECEIVED
    ↓
 CLAWED_BACK
```

- `EXPECTED`: created at funding.
- `PARTIALLY_RECEIVED` / `RECEIVED`: **operator action** —
  `POST /admin/commissions/{id}/receipts` records a received-amount entry
  (new: does `Commission` need a `received_amount` ledger, or is a single
  `received_amount` field on the row — which already exists — sufficient?
  Given `CommissionAdjustment` already exists for corrections, proposing
  the existing `received_amount` field is updated directly by this
  endpoint rather than adding a new receipts table, and status flips to
  `PARTIALLY_RECEIVED` or `RECEIVED` based on
  `received_amount vs expected_amount + adjustments`.
- `CLAWED_BACK`: an operator records a clawback via the *existing*
  `create_commission_adjustment` endpoint (already supports arbitrary
  `adjustment_type`, already idempotent) rather than a new endpoint —
  `CLAWBACK` is just an adjustment type, matching what the test written in
  the last pass already exercises.

### CommissionSplit

`CommissionSplit` (recipient_type, recipient_reference, percentage,
amount, status) exists with zero write path. Proposed:
`POST /admin/commissions/{id}/splits` — operator defines how a commission
divides across recipients (e.g. affiliate + house), idempotent, validates
percentages sum to ≤100% or amounts sum to ≤`expected_amount`.

## 4. Renewal engine

`RenewalOpportunity` has both `eligibility_status` and `status` fields —
proposing a clear split rather than guessing at the existing intent:

- `eligibility_status` (computed, not operator-set): `PENDING` →
  `ELIGIBLE` / `INELIGIBLE`. Set by a renewal-evaluation worker.
- `status` (the sales/ops pipeline stage, operator-driven):
  `PENDING` → `OPPORTUNITY_CREATED` → `CONTACTED` → `CONVERTED` /
  `DECLINED` / `EXPIRED`.

### Worker: renewal evaluation

Proposed: a scheduled worker step (same worker process as
`app/worker.py`'s outbox loop, a new periodic pass) that scans `Funding`
rows with `status="FUNDED"` and `funding_confirmed_at` older than a
configurable eligibility window (open question 2), creates a
`RenewalOpportunity` (`eligibility_status="ELIGIBLE"`) if one doesn't
already exist for that `funding_id` (the model's `unique=True` on
`original_funding_id` already enforces one-per-funding), and emits
`renewal.eligible.v1` — which `app/notification_policy.py` already marks
as requiring marketing consent-awareness (`policy.marketing` check in
`channels_for_event`) since renewal outreach is a marketing-adjacent
communication.

### Endpoints

- `GET /applications/{id}/renewal-opportunities` (borrower + admin read)
- `POST /admin/renewal-opportunities/{id}/status` — operator moves the
  pipeline `status` (`CONTACTED`, `CONVERTED`, etc.), idempotent.

## Open questions — need your decision before I build any of this

1. **Commission rate source — partially answered.** You said this is
   based on standard US business-loan-commission conventions. Every
   `product_type` in this codebase so far is `WORKING_CAPITAL`
   (alternative/MCA-style lending, not SBA/bank term loans), where US
   broker commissions are typically cited in the ~6-12% range of funded
   amount (higher than traditional term-loan/SBA commissions, which run
   ~1-3%, because terms are shorter and deals turn over faster). Proposing
   as a concrete, overridable default: `commission_rate_bps: int = 800`
   (8%) added to `LenderProgram` — varies per lender/product since that's
   already the natural per-deal-type scope in this schema, with the
   `Commission.expected_amount` calculation reading it at funding time
   (not hardcoded, so any specific program can be set differently).
   **Confirm**: is 8% the right default/starting point, or do you have an
   actual number (or a per-program range) from how this business
   negotiates broker commissions today? And does the rate live on the
   `LenderProgram` (per product/lender) as proposed, or does it need to be
   negotiable per individual `Offer` instead?
2. **Renewal eligibility window.** What makes a funded account eligible
   for a renewal opportunity — a fixed time since funding (e.g. 90 days),
   a fraction of the term elapsed, a minimum payment history, or something
   else? I don't have a defensible default to propose here without your
   input; "some number of days" would be a guess.
3. **Contract creation vs. send as one step or two.** Proposed above as
   one worker step (`DRAFT` immediately followed by `SENT`). If
   `send_envelope` should be independently retryable (e.g. so a DocuSign
   outage doesn't block the `Contract` row from existing and being
   visible to the borrower), it should be two separate outbox-driven
   steps instead. Which failure mode matters more here?
4. **Multi-signer contracts.** `ESignAdapter.send_envelope` takes a single
   `signer_email`/`signer_name`. `app/models.py`'s `Owner` model supports
   multiple owners per application. Does every contract need every >X%
   owner's signature, or is a single authorized signer (e.g. the
   application's primary contact) sufficient for v1?
5. **Who can approve `APPROVED_FOR_FUNDING`/`funds-sent`/`confirm`?** These
   move real money. Proposing new granular permissions
   (`funding.approve`, `funding.funds_sent`, `funding.confirm`) rather
   than reusing the existing broad `commission.adjust`-style permissions,
   so these can be governed separately (e.g. requiring a different role
   or dual-control later) — confirm that's the right granularity, not
   over- or under-engineered for how this team actually operates.

## What I'll do once these are answered

Same working method as every other pass in this mission: implement one
state machine at a time (Contract, then Funding transitions, then
Commission, then Renewal — in that order, since each depends on the
previous), with the idempotency/audit pattern already proven, tests that
drive the real HTTP flow the way `tests/test_admin_commission_adjustments.py`
does, `scripts/verify_openapi_contract.py`-clean commits (surgical patches,
not wholesale regeneration), pushed to PR #33 pass by pass.
