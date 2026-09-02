# Redis production and recovery contract

MoneyBee uses Redis for distributed rate-limit counters. Those counters are reconstructible and their loss does not remove PostgreSQL business state, but Redis unavailability deliberately fails protected public/webhook requests closed. Queue, session, lock, or durable job use must be documented before activation.

The data Compose enables AOF with `appendfsync everysec` and a persistent `/data` mount. The server mission must verify ACLs, last persistence status, volume durability, restart recovery, memory policy, and application reconnect behavior. Documentation alone never sets `REDIS_RECOVERY_STATUS=PASS`.
