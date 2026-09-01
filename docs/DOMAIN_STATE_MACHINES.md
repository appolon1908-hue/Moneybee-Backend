# MoneyBee domain state machines

Updated: 2026-09-01

The backend is the authority for every state transition. Frontends display the returned state and available actions; they do not construct approval, funding, filing or delivery states locally.

## Financing application

The canonical transition map is implemented in `app/services.py`. An absent edge is rejected.

| Current state | Allowed next state(s) |
| --- | --- |
| `APPLICATION_STARTED` | `APPLICATION_IN_PROGRESS`, `READY_FOR_MATCHING`, `WITHDRAWN` |
| `APPLICATION_IN_PROGRESS` | `APPLICATION_COMPLETE`, `READY_FOR_MATCHING`, `FRAUD_REVIEW`, `COMPLIANCE_REVIEW`, `WITHDRAWN` |
| `APPLICATION_COMPLETE` | `VERIFICATION_PENDING`, `READY_FOR_MATCHING`, `FRAUD_REVIEW`, `COMPLIANCE_REVIEW` |
| `VERIFICATION_PENDING` | `READY_FOR_MATCHING`, `FRAUD_REVIEW`, `COMPLIANCE_REVIEW`, `DECLINED` |
| `FRAUD_REVIEW` | `READY_FOR_MATCHING`, `COMPLIANCE_REVIEW`, `DECLINED` |
| `COMPLIANCE_REVIEW` | `READY_FOR_MATCHING`, `DECLINED` |
| `READY_FOR_MATCHING` | `MATCHED`, `DECLINED`, `FRAUD_REVIEW` |
| `MATCHED` | `SUBMITTED_TO_LENDERS`, `OFFERS_AVAILABLE`, `DECLINED` |
| `SUBMITTED_TO_LENDERS` | `UNDERWRITING`, `CONDITIONS_PENDING`, `OFFERS_AVAILABLE`, `DECLINED` |
| `UNDERWRITING` | `CONDITIONS_PENDING`, `OFFERS_AVAILABLE`, `DECLINED` |
| `CONDITIONS_PENDING` | `CONDITIONS_COMPLETE`, `OFFERS_AVAILABLE`, `DECLINED` |
| `OFFERS_AVAILABLE` | `OFFER_ACCEPTED`, `EXPIRED`, `DECLINED` |
| `OFFER_ACCEPTED` | `CONDITIONS_PENDING`, `CONTRACT_READY`, `CANCELLED` |
| `CONDITIONS_COMPLETE` | `CONTRACT_READY`, `CANCELLED` |
| `CONTRACT_READY` | `CONTRACT_SENT`, `CANCELLED` |
| `CONTRACT_SENT` | `CONTRACT_SIGNED`, `EXPIRED`, `CANCELLED` |
| `CONTRACT_SIGNED` | `APPROVED_FOR_FUNDING`, `CANCELLED` |
| `APPROVED_FOR_FUNDING` | `FUNDS_SENT`, `CANCELLED` |
| `FUNDS_SENT` | `FUNDED`, `COMPLIANCE_REVIEW` |
| `FUNDED` | `CLOSED` |

`DECLINED`, `WITHDRAWN`, `EXPIRED`, `CANCELLED` and `CLOSED` have no ordinary forward edge in the central transition map. Corrective operations must be explicit, authorized and audited rather than silently rewriting history.

### Transition requirements

Every application transition must:

1. load the authorized application;
2. validate the edge against the canonical map;
3. validate domain preconditions;
4. persist the new state and audit/timeline evidence in one transaction;
5. enqueue provider work only after durable state exists;
6. return an explicit conflict/problem document when the resource changed or the edge is illegal.

## Matching and lender submission

```text
READY_FOR_MATCHING
  -> versioned program evaluation
  -> MATCHED
  -> prepared lender submissions
  -> SUBMITTED_TO_LENDERS
  -> UNDERWRITING / CONDITIONS_PENDING / OFFERS_AVAILABLE / DECLINED
```

Matching stores program version, eligibility, score and reasons. Re-running matching replaces the application’s current match set transactionally; it must not append contradictory active results. Live lender transmission additionally requires the lender provider and `lenders.live_submission` capability.

## Offer and disclosure

```text
lender offer created
  -> AVAILABLE
  -> commercial-financing disclosure generated
  -> borrower/admin reads exact disclosure snapshot
  -> acknowledgment recorded once under authenticated subject
  -> offer acceptance follows its separate guarded operation
```

Rules:

- Amount financed, finance charge, total repayment, payment schedule, term, APR/APR-equivalent and prepayment text are backend values.
- The disclosure snapshot is tied to one offer and one application.
- Acknowledgment requires an idempotency key and row lock.
- `acknowledged_by` comes from the authenticated principal, never request JSON.
- The first response and an idempotent replay serialize the same evidence.
- Acknowledgment is not acceptance of the offer and does not move money.

## Conditions

```text
BORROWER_ACTION_REQUIRED
  -> SUBMITTED
  -> SATISFIED | REJECTED | WAIVED
```

The concrete labels are those returned by the existing condition models/routes. Borrowers may submit requested evidence; lender/admin capabilities control approval, rejection or waiver. Invalid repeat or cross-role actions are rejected.

## Adverse-action notice evidence

```text
DECLINE underwriting decision
  -> GENERATED notice snapshot
  -> optional capability-controlled delivery workflow
  -> delivery evidence/status update
```

The generated notice preserves creditor identity, principal reasons and rendered notice text. Generation does not prove delivery. The global compliance page therefore distinguishes total notices from records still lacking delivery evidence.

## Commission tax evidence

```text
commission splits recorded
  -> tax-year aggregation generated/recomputed
  -> requires_1099 determined
  -> recipient name/TIN evidence completed
  -> external filing performed by approved process
  -> filing reference and timestamp recorded
```

Rules:

- Generation recomputes from authoritative commission split rows; it does not accumulate a second total on replay.
- TIN is encrypted and write-only. API responses expose `tin_present` only.
- Filing evidence is idempotent. A different filing reference cannot overwrite an existing filed record.
- Recording filing evidence does not transmit a tax filing.

## Funding and money movement

The application path reaches `APPROVED_FOR_FUNDING`, `FUNDS_SENT` and `FUNDED` only through authorized backend operations. Repository presence of those routes does not activate live movement.

Required safeguards:

- amount and currency are authoritative decimal values;
- transition and financial evidence commit atomically;
- ambiguous provider responses create explicit operational/reconciliation work;
- provider calls use durable intent/outbox patterns;
- live payment/funding capabilities remain disabled until separately certified.

## Integration delivery

```text
business transaction
  -> durable outbox/inbox record
  -> leased worker attempt
  -> delivered | retryable failure | terminal operational exception
```

A request handler must not report provider success merely because local validation succeeded. Requeue operations are explicit, authorized and idempotent where supported. The admin control plane exposes queued, failed and exception records without bypassing provider gates.

## Capability lifecycle

```text
NOT_CONFIGURED / disabled
  -> CONFIGURED
  -> VERIFYING
  -> READY
  -> DEGRADED | DISABLED
```

A feature is effective only when its capability is enabled and any required provider connection is ready. Health, UI visibility or a configured route alone cannot activate live behavior.
