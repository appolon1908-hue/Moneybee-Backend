# Production recovery contract

Production certification requires evidence for a current encrypted PostgreSQL base backup, continuous bounded WAL archiving, an access-controlled off-host copy, isolated restore, application start against the restored database, and Redis recovery/rebuild behavior.

Required evidence: source SHA and image digests, Alembic head, backup reference/timestamp/checksum, WAL range and target time, off-host retrieval result, restore destination and duration, validation counts, effective RPO/RTO, Redis classification, and rollback digest. Values are supplied outside Git through `BACKUP_STATUS`, `PITR_STATUS`, `OFFHOST_BACKUP_STATUS`, `RESTORE_STATUS`, `REDIS_RECOVERY_STATUS`, and `APPLICATION_RESTORE_STATUS`. Only literal `PASS` backed by retained evidence satisfies certification.

Recovery order: provision isolated PostgreSQL → restore base backup → replay WAL to the approved target → validate schema/data/roles → recover or rebuild Redis → inject secrets from the approved authority → start migration check, API, then workers with external effects disabled → verify health/readiness and representative safe operations → restore routing only after approval.
