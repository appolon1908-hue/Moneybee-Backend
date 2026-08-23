# Production readiness gate

This repository is a production-oriented baseline, not launch authorization.

Before launch, all of the following must be evidenced:
1. Production Postgres backups, point-in-time recovery, restore drill, encrypted storage, and restricted roles.
2. Redis persistence/HA decision and queue worker/DLQ implementation for asynchronous integrations.
3. Keycloak production client/roles/audience configuration and authorization tests for every role.
4. Vendor contracts, credentials, sandbox certification, webhook signing rules, retry policies, and reconciliation for Plaid/KYB/KYC/credit/e-sign/email/SMS/lenders.
5. Immutable image build, SBOM, vulnerability scan, secret scan, signed release, protected deployment environment, rollback rehearsal, and monitoring/alerting.
6. Privacy, adverse-action, lending/broker disclosures, consent evidence, data retention/deletion, and jurisdiction-specific legal review.
7. Load, concurrency, failure-injection, migration rollback, backup restore, and disaster-recovery tests.
8. Live lender submission and live funding capability flags must remain false until the go-live change is approved.
