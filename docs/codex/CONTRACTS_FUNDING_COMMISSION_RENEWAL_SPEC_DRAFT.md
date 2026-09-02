# Contracts, funding, commission, and renewal engines — historical design spec

> Status (2026-09-02): IMPLEMENTED. This document is retained as design and
> decision history. The executable authority is the current domain services,
> workers, Alembic migrations, and their contract/concurrency regression tests.
> Any future discrepancy must be resolved in favor of tested current behavior
> and recorded as a new design decision; this file is not a launch checklist.

Status: **approved to build.** The one substantive business decision
(commission is deal-negotiated, splittable across brokers) is confirmed;
the remaining lower-stakes questions are defaulted below, each flagged
and one grep away to change. Implementation proceeds per the order at the
bottom, one tested pass at a time against PR #33.

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

Created as part of the same `POST /admin/fundings/{id}/confirm` operator
action that moves `Funding.status → FUNDED` (see open question 1,
resolved) — the operator supplies the negotiated `commission_rate_bps`
(or a direct `expected_amount`) at that moment, since the rate is
deal-specific rather than a stored default. One `Commission` row
(`status="EXPECTED"`), `expected_amount = funded_amount *
commission_rate_bps / 10000`.

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

## Open questions — resolved or defaulted, all overridable

1. **Commission rate source — resolved.** Commission is a percentage of
   the loan (funded) amount, negotiated per deal rather than a single
   fixed platform-wide rate, and splittable across multiple brokers on
   the same deal. This confirms the existing (already-modeled,
   never-written-to) `CommissionSplit` table
   (`recipient_type`/`recipient_reference`/`percentage`/`amount`) is
   exactly the right shape — no new split-tracking model needed.
   Revised design from the original proposal: rather than a stored
   `commission_rate_bps` default on `LenderProgram` (which implied one
   fixed rate per program), the rate/amount is **entered by the operator
   at the point of funding confirmation** — `POST
   /admin/fundings/{id}/confirm` (the trigger below) now additionally
   accepts `commission_rate_bps` (or a direct `expected_amount` override,
   for cases where the split doesn't cleanly compute from a flat rate),
   which both records the deal-specific number and computes
   `Commission.expected_amount = funded_amount * commission_rate_bps /
   10000`. Splitting across brokers is a separate, subsequent operator
   step via `POST /admin/commissions/{id}/splits` (proposed below,
   unchanged) once the total commission exists. No `LenderProgram` schema
   change needed for this after all.
2. **Renewal eligibility window — defaulting, not confirmed.** No signal
   from you yet on what makes a funded account eligible, and "some number
   of days" is a guess I don't want to hide. Proceeding with **90 days
   since `funding_confirmed_at`**, a common working-capital/MCA renewal
   benchmark, as a named, isolated constant
   (`RENEWAL_ELIGIBILITY_DAYS = 90` in one place) specifically so it's a
   one-line change, not a re-architecture, when you give me the real
   number or rule (elapsed-term-fraction, payment-history-based, etc.).
3. **Contract creation vs. send — defaulting to one step.** `DRAFT`
   immediately followed by `SENT` in the same worker step. Simpler, and
   two-step (independently-retryable send) is a mechanical split to make
   later if a real DocuSign-outage incident shows it's needed — not
   worth the extra complexity speculatively.
4. **Multi-signer contracts — defaulting to single signer for v1.** Your
   "1 or multiple" read as leaving it to me: going with **one authorized
   signer** (the application's primary contact/owner) rather than
   requiring every >X% owner. Multi-signer sequencing (who signs first,
   what happens on partial completion) is real added complexity that
   isn't justified until a specific deal needs it — flagging this as the
   default most likely to need revisiting once real commercial contracts
   are in play.
5. **Funding-approval permissions — proceeding with the granular
   proposal.** `funding.approve` / `funding.funds_sent` / `funding.confirm`
   as three separate permissions (not one), so who can move money can be
   governed independently per step later (e.g. dual control on
   `funds_sent`) without a schema change then.

All defaults above are recorded here specifically so they're one grep
away to find and change — nothing is hidden in code comments only.

## Implementation order

Building in dependency order, each as its own tested, pushed pass to PR
#33, same discipline as every prior pass (real local checks before every
push, idempotency on every money-moving write, surgical
`verify_openapi_contract.py`-clean patches, mission doc checked off as
each lands):

1. Funding state machine (the six-stage transition sequence + the four
   operator endpoints) — the backbone everything else hangs off of.
2. Contract/e-sign engine (DRAFT→SENT→SIGNED, DocuSign webhook consumer).
3. Commission engine (creation at funding-confirm with operator-entered
   rate, receipts, splits) — depends on step 1's `confirm` endpoint
   existing to attach to.
4. Renewal engine (eligibility worker + pipeline-status endpoint) — least
   urgent, no other engine depends on it.
