# MoneyBee system review — architecture, code, API, and security

Original review: 2026-08-28  
Remediation update: 2026-09-01

This document records the review findings and their current disposition. It is
source-side evidence only; it does not authorize a production deployment or any
live provider capability.

Companion frontend evidence lives in `moneybee-frontend-/docs/`.

## Current assessment

MoneyBee now has a substantial production-oriented backend foundation:

- async FastAPI and SQLAlchemy;
- explicit organization tenancy and portal/client boundaries;
- `/api/v2` as the canonical contract with a deprecated `/api/v1` compatibility alias;
- transactional outbox/inbox patterns for provider work;
- fail-closed provider capability checks;
- structured request logging and problem responses;
- bounded public/webhook rate limiting;
- versioned field encryption and rewrapping support;
- double-entry financial records;
- generated OpenAPI and endpoint-catalog checks;
- PostgreSQL migration, rollback, identity, tenancy, API and release-image CI.

The branch also adds complete operator/borrower compliance APIs for adverse-action
notices, commercial-financing disclosures and commission tax evidence. The
remaining launch requirements are primarily environment evidence, approved
provider configuration, legal/compliance approval and controlled staging/production
activation—not missing source routes disguised as operational readiness.

## Disposition of review findings

### CI action integrity — closed in this branch

The original review overstated the whole pipeline by saying every action was
SHA-pinned. At that time, `.github/workflows/ci.yml` still used mutable major tags.
The primary workflow and hardened workflow now use immutable action commit SHAs,
including checkout, Python setup, artifact upload, Buildx, image build and Trivy.

CI also performs private-key scanning, static checks, application tests, OpenAPI
verification, migration upgrade/rollback and digest-oriented release validation.

### Currency crossing a binary-float boundary — closed for the identified portal fields

The original review incorrectly said every currency value was already `Decimal`.
Two portal schemas contradicted that statement:

- lender-program amount update fields accepted `float`;
- lender bank-transaction response amounts used `float`.

Those fields now use constrained `Decimal` values, and tests exercise exact values
such as `0.10`. Financial ledger commands and database money columns already use
`Decimal`/`Numeric`.

Any future monetary request/response field must use `Decimal` or a documented
integer-minor-unit representation. A binary float is not an acceptable financial
authority boundary.

### Strict request schemas — partially complete; claim corrected

The original review incorrectly described all Pydantic request schemas as
`extra="forbid"`. Strict rejection is present on financial commands and selected
newer command models, but several legacy application, intake and portal models
still inherit Pydantic's default extra-field behavior.

This is a compatibility-sensitive consistency gap, not proof that the API accepts
mass assignment: route services still select explicit model fields and enforce
permissions. New security/financial/compliance command models should use
`extra="forbid"`; legacy models should migrate deliberately with client contract
tests rather than through one unreviewed breaking switch.

### `/api/v1` portal-client boundary — closed in this branch

The original review correctly identified a security bypass: portal-client
classification previously recognized only `/api/v2`, even though the same routers
were also mounted under `/api/v1`.

Both portal-client enforcement implementations now normalize `/api/v1` to the
canonical `/api/v2` path before classifying borrower, lender, administrator,
application, offer and condition routes. Boundary tests cover correct and
cross-portal client IDs for both prefixes. The compatibility alias therefore does
not weaken the `azp`/client-ID boundary.

The alias remains deprecated, is hidden from OpenAPI, and receives deprecation and
sunset headers. New clients must use `/api/v2`.

### Enabled-provider startup validation — closed for supported provider modes

The original validator covered several providers but omitted generic HTTP CRM,
KYB, credit and lender modes plus DocuSign. In staging and production, every
supported enabled mode now requires its minimum credentials/configuration before
the process can start:

- Plaid and external bank credential store;
- Codestra middleware;
- generic HTTP or Odoo CRM;
- generic HTTP or Middesk KYB;
- generic HTTP or Experian credit;
- generic HTTP lender submission;
- DocuSign;
- SendGrid;
- Twilio;
- S3 object storage;
- ClamAV;
- Stripe or PayPal.

Tests cover both incomplete rejection and complete acceptance for the newly added
provider modes. Runtime capability readiness still remains a separate requirement;
valid credentials do not automatically enable delivery.

### Field-encryption rotation — closed in the current implementation

The original review described a single static Fernet key. The current implementation
uses a key map, prefixes ciphertext with its key version, requires an active key
version, can decrypt older configured versions and provides `rewrap_secret()` for
incremental rotation. TIN and provider-credential APIs do not return encrypted or
plaintext secret values.

Operational key-retirement procedure and restore evidence are still required before
production certification.

## Architecture

### Strengths

- Provider adapters are selected through explicit registries and protocols.
- External delivery is separated from request acceptance through durable records
  and worker leases.
- Application transitions are centralized and illegal edges are rejected.
- Financial postings, commission evidence, tax records and disclosures have
  explicit database models rather than being reconstructed from UI text.
- Canonical endpoint and product-flow maps are documented in:
  - `docs/API_ENDPOINT_CATALOG.md`
  - `docs/MONEYBEE_PRODUCT_API_MATRIX.md`
  - `docs/API_CONVENTIONS.md`
  - `docs/DOMAIN_STATE_MACHINES.md`

### Remaining structural work

- Legacy and newer domain modules still use more than one organizational pattern.
  Consolidation should be incremental and behavior-preserving, not a framework
  rewrite.
- Several legacy request models should move to strict unknown-field rejection after
  client compatibility is proven.
- Some broad dictionary response fields in legacy workspace schemas should be
  replaced by explicit typed submodels over time.
- Provider activation still requires secret binding, network reachability,
  sandbox/staging evidence, alerting, reconciliation and rollback proof.

## API design and security

### Canonical behavior

- `/api/v2` is authoritative.
- Every new endpoint requires a unique operation ID and explicit response model.
- Errors converge on `application/problem+json` with a stable code and request ID.
- Request and correlation IDs propagate through the centralized middleware/client.
- Portal tokens are checked against the allowed client IDs for the target route.
- Organization membership and resource ownership are enforced server-side.
- Financial/compliance mutations use row locks, optimistic versions, uniqueness or
  idempotency according to the operation.

### Compliance API added by this remediation

The branch adds:

- compliance overview;
- paginated/filterable adverse-action notices;
- paginated/filterable commercial-financing disclosures;
- paginated/filterable commission tax records;
- idempotent tax-record generation;
- encrypted, write-only TIN updates;
- idempotent filing-reference evidence;
- borrower-owned disclosure read and acknowledgment;
- administrator disclosure acknowledgment.

Disclosure acknowledgment attributes the authenticated subject and ignores spoofed
client actor fields. Tax responses expose only `tin_present`; recording filing
evidence does not transmit a filing.

## Testing and release evidence

Required exact-head gates include:

- private-key scan;
- Ruff and compileall;
- one Alembic head;
- empty PostgreSQL upgrade;
- application tests on PostgreSQL;
- migration downgrade/upgrade round-trip;
- OpenAPI and additive manifest verification;
- generated endpoint-catalog drift check;
- identity, tenancy and portal-client boundary tests;
- API/worker/migration release-image builds;
- critical/high image vulnerability policy;
- fail-closed Compose/runtime configuration checks.

Frontend CI checks out an exact backend contract ref, exports OpenAPI, verifies
frontend routes, typechecks, tests and builds/scans the marketing, borrower, lender
and administrator applications.

## Production boundary

Source completion is not production certification. Production remains blocked until
all required runtime evidence is current, including:

- approved immutable image digests and source locks;
- external secret binding without plaintext Git material;
- database backup and tested restore evidence;
- Keycloak client/role/scope verification;
- Kong/Caddy route and security-header verification;
- provider sandbox/staging tests;
- finance/compliance/legal owner approval;
- monitoring and actionable alerts;
- canary and rollback proof;
- explicit authorization before enabling any live delivery or money movement.

No change in this pull request modifies SSH access, deploys a server, files a tax
form, sends a notice, submits to a lender or moves money.
