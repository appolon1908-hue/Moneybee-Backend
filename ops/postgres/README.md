# PostgreSQL role hardening

These assets are for the later controlled server rollout; repository CI must never run them against production.

Run `role-hardening.sql` as the protected `moneybee_admin` identity after a verified backup. Supply passwords through the approved secret mechanism separately; this SQL contains none. Existing application objects must be transferred to `moneybee_migrator` using the reviewed bootstrap procedure before Alembic changes them. Then connect as `moneybee_runtime` and run `verify-runtime-role.sql`.

The scripts refuse a database other than `moneybee`, grant no access to unrelated databases, and establish default privileges for objects subsequently created by the migrator.
