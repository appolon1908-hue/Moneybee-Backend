# Secure MoneyBee staging deployment scaffold

## Current safety state

The designated staging candidate is `49.12.145.107`. It is **not runtime-path verified**.
`deploy/runtime-paths.lock.json` and `deploy/release.lock.json` are intentionally
`UNVERIFIED`, so the deployment-readiness workflow cannot pass. This scaffold does not
connect to, modify, restart, or deploy the server.

## Docker ownership boundary

Backend-owned images are built only from `Moneybee-Backend`:

- `moneybee-api`
- `moneybee-worker`
- `moneybee-migrate`

Frontend-owned images are built only from `Moneybee-frontend-`:

- `moneybee-marketing`
- `moneybee-borrower`
- `moneybee-lender`
- `moneybee-admin`

The backend repository no longer needs a sibling frontend checkout for deployment.
Digest-only Compose fragments join through reviewed external Docker networks:

- `moneybee_internal`
- `moneybee_edge`

The server must never run `docker compose build` for a release.

## Required GitHub environments

Configure these environments with required reviewers:

- `staging-preflight`: read-only SSH evidence capture
- `staging-release`: immutable image publication
- `staging-deploy`: readiness-packet approval

Production is not included in this scaffold.

## Required backend repository variables

- `PYTHON_BASE_IMAGE`, including `@sha256:...`
- `TRIVY_IMAGE`, including `@sha256:...`

The frontend release workflow has separate base-image and public build variables.

## Required environment secrets

For `staging-preflight` only:

- `MONEYBEE_STAGING_SSH_PRIVATE_KEY`
- `MONEYBEE_STAGING_KNOWN_HOSTS`

Use a read-only or forced-command SSH principal. Do not replace strict known-host
verification with `ssh-keyscan` during a release.

## Runtime-path verification

Run `runtime-path-preflight-read-only` manually. It performs only read operations and
produces:

- `runtime-preflight.raw.txt`
- `runtime-paths.candidate.json`
- a SHA-256 digest binding the evidence

Review the observed hostname and host key, current workloads, occupied ports, Docker
networks, filesystem ownership, free space, reverse-proxy ownership, data locations,
backup location, and SSH permissions. Then submit a separate PR that changes
`deploy/runtime-paths.lock.json` to `VERIFIED`, records the reviewed hostname, fills the
absolute paths, selects `external` or `compose` data mode, and records the exact evidence
SHA-256.

## Release lock

Backend and frontend image workflows publish repository-owned images with:

- exact source SHA labels
- immutable registry digests
- BuildKit SBOM and provenance
- Trivy HIGH/CRITICAL gate
- GitHub artifact attestations
- a release-manifest artifact

A separate reviewed release-lock PR must place exact backend, frontend, PostgreSQL,
Redis, and Caddy digests plus the reviewed ACME contact email into
`deploy/release.lock.json`. All live and external capabilities must remain false.

Compute the release lock `configuration_checksum` from the exact backend and
frontend deployment fragments with:

```bash
python ops/compute-configuration-checksum.py \
  --frontend-root ../Moneybee-frontend- \
  --json
```

The staging readiness-packet workflow uses the same command and fails closed if the
committed `deploy/release.lock.json` checksum differs from the reviewed fragments.

## Runtime environment gate

Before any future deployment executor pulls an image or starts a container,
`ops/verify-runtime-env.py` must check the server-owned backend environment file. It
rejects group/world-readable files, local auth bypass, runtime schema creation,
noncanonical Keycloak settings, unreviewed CORS origins, provider activation, live
financial or communication flags, SQLite/localhost data URLs, missing field encryption,
and release-evidence values that do not match the reviewed release lock.

## Readiness packet and remote-deployment boundary

`staging-deployment-readiness-packet` validates VERIFIED locks, checks out the exact
frontend SHA, verifies the combined configuration checksum, and creates a deterministic
review artifact. It contains no SSH step and cannot change `49.12.145.107`.

`ops/deploy-staging.sh` is intentionally a fail-closed stub. A functional remote
deployment executor must be added in a separate PR only after runtime paths, host
identity, backup/restore evidence, immutable image digests, environment values, and
rollback ownership have been reviewed.

The eventual initial staging rollout may start PostgreSQL and Redis only when reviewed
`data_mode=compose`, followed by migration, API, marketing, borrower, lender, admin, and
Caddy. It must not start the external-delivery worker. CRM/Odoo, n8n, email, SMS, credit,
lender submission, e-sign, funding, payment, and payout capabilities remain disabled.

## Rollback

Application rollback uses a previously reviewed release directory and immutable
digests. Database downgrade is never automatic. Before deployment, record a verified
backup reference and exercise restore. If a schema change is not backward compatible,
use a reviewed forward fix or a separately approved database recovery procedure.

## Required merge order

1. Merge the accepted backend application lineage.
2. Merge this deployment-scaffold PR.
3. Merge the accepted frontend application lineage.
4. Merge the paired frontend deployment-scaffold PR.
5. Create and protect `release/staging`.
6. Publish exact-SHA backend and frontend images.
7. Review runtime-path and release-lock PRs.
8. Generate and review the staging readiness packet.
9. Add and independently review a host-specific deployment executor.
10. Deploy staging only after both locks are `VERIFIED`; no executor exists in this PR.
