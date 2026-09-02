# Live migration standard

Production-sensitive changes follow **expand → backfill → validate → switch → contract**.

1. Expand with nullable columns, additive indexes, and compatibility reads/writes.
2. Backfill in bounded resumable batches without logging plaintext or holding a table-wide transaction.
3. Validate counts, constraints, application reads, lookup-token uniqueness, and rollback compatibility.
4. Switch the reviewed immutable release to the new representation.
5. Contract only after server evidence proves the old release is no longer needed.

Constraints on large tables use staged validation where PostgreSQL permits it. A migration must document lock level, expected duration, downgrade/forward-fix behavior, and whether the preceding image remains compatible. Destructive PII conversion and compatibility-column removal are prohibited in the initial rollout.
