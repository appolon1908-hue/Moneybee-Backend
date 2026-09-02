# Production hardening plan

This document is the implementation ledger for the production-hardening blueprint.
MoneyBee must not report production readiness until every mandatory gate is
implemented and backed by current evidence.

## Production-hardening-20260902 reconciliation

Preserved baseline: the historical sections below describe the state before this branch and are retained as audit history.

DONE in repository code and tests: separate migration/runtime Compose identities; explicit migration URL fail-closed behavior; fresh-cluster admin identity; least-privilege role assets; runtime-role readiness inspection; Redis-backed distributed rate limiting; trusted-proxy traversal; versioned encryption envelope with legacy reads; document quarantine/scanner foundation; financial locking/idempotency foundations; durable inbox/outbox retry foundations; and recovery evidence fields.

PARTIAL pending complete repository evidence: command inventory/coverage, PII expand/backfill/reveal across all inventoried plaintext fields, complete OpenTelemetry metrics/alert implementation, and exhaustive PostgreSQL concurrent-transition coverage.

OPEN operational evidence: immutable published digests, off-host backup, PITR, isolated restore, Redis recovery, staging E2E, rollback rehearsal and production canary. Runbooks or configuration do not make these PASS.

## Implemented in this phase

- Command context and typed AcceptOfferCommand foundation.
- Production-required If-Match for offer acceptance.
- Database row locking and aggregate-version conflict responses for offer acceptance.
- Versioned offer.accepted.v1 events with aggregate version, tenant, correlation,
  and causation metadata.
- Expanded outbox delivery evidence: destination, attempt timestamps, delivery
  timestamp, HTTP status, and stable error code.
- Durable operational exceptions created when outbox retries are exhausted.
- Read-only operational-exception catalog plus an audited admin resolution action.
- Machine-readable GET /api/v2/admin/system/readiness.
- Release-evidence settings for source SHA, immutable image digests, migration
  head, configuration checksum, SBOM, provenance, backup, restore, and staging.
- Readiness remains PARTIAL whenever evidence or architecture gates are missing.

## Existing foundations retained

- Canonical OIDC issuer https://auth.codestra.co/realms/codestra.
- Request idempotency, audit records, leased outbox, and durable inbox.
- Codestra for asynchronous business integrations.
- Direct MoneyBee adapters for Plaid, Middesk, Experian, lenders, and DocuSign.
- Odoo Community as a CRM projection, never lending authority.
- Provider and capability gates disabled by default.

## Mandatory remaining gates

1. Convert every meaningful mutation to a typed command and shared command handler.
2. Enforce optimistic concurrency on applications, submissions, conditions,
   contracts, funding, commissions, and other financial aggregates.
3. Complete aggregate-specific transition policies and concurrency tests.
4. Add approved inbox translators and workers; webhook handlers must remain
   persistence-only.
5. Add notification intents, channel deliveries, templates, and suppression records.
6. Implement upload session, quarantine, malware scan, classification, extraction,
   and document-review workflows.
7. Add masked PII views, reasoned reveal authorization, reveal audit, key versions,
   and rotation.
8. Add provider circuit breakers, rate-limit handling, health transitions, and
   recovery controls.
9. Add OpenTelemetry, structured logs, Prometheus metrics, dashboards, worker
   heartbeats, and actionable alerts.
10. Adopt expand/backfill/validate/contract migrations for live schema changes.
11. Produce immutable images, SBOM, provenance, signatures, staging evidence,
    restore rehearsal, canary evidence, and rollback evidence.
12. Complete record-level security, webhook-race, worker-crash, cross-tenant,
    document-malware, and financial double-action tests.

## Readiness contract

The readiness endpoint reports runtime/provider state and supplied release evidence.
It intentionally lists structural blockers that cannot be inferred from a successful
health check. FINAL_STATUS=READY is permitted only in production with no blockers.

Release automation—not application developers—must supply real evidence values.
Placeholders, latest tags, unverified backups, or configuration without a tested
restore do not satisfy the gate.

## Safe implementation order

identity binding -> command coverage -> authorization policies -> concurrency ->
event contracts -> outbox/inbox workers -> operational recovery -> notification
subsystem -> secure documents -> PII controls -> observability -> staging and
restore proof -> immutable release and canary.
