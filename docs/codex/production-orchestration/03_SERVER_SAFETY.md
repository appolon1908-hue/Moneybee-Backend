# Phase 03 — Server discovery, backup, restore and database authority

Phase ID: `MONEYBEE_PHASE_03_SERVER_SAFETY`

Predecessor: Phase 02 `GO` and a verified complete release lock.

Target: `49.12.145.107`

## Objective

Establish a trustworthy, reversible production baseline before installing MoneyBee. Perform read-only discovery first, preserve all existing workloads, prove backup and isolated restore, and establish separate migration/runtime database authority.

## 1. Verify the release lock before server access

From the deployment controller:

- fetch the authoritative runtime repository at its exact locked SHA;
- run the release-lock verifier;
- verify all source SHAs, image digests, checksums, signatures and initial capability flags;
- verify the target host is exactly `49.12.145.107`;
- record the operator identity, change ID and UTC start time.

If verification fails, do not connect to the host.

## 2. Read-only server inventory

Do not change SSH configuration, users, keys, sudo rules or firewall policy.

Capture without mutation:

```text
hostname and host identity
OS and kernel
CPU, memory and load
filesystem usage, inode usage and mount map
container engine and Compose/runtime versions
running/stopped containers and health
images and digests
networks, listeners and published ports
volumes, bind mounts and data ownership
existing reverse proxies and ingress configuration
existing Keycloak/Kong/Caddy/Redis/PostgreSQL/OpenBao/Odoo/n8n/observability workloads
systemd units, timers and scheduled jobs related to the platform
current runtime directories and Git checkouts
firewall and network exposure from approved read-only commands
DNS resolution from the host and external resolvers
TLS certificate state for all MoneyBee domains
existing backup jobs and latest successful artifacts
current alerts and monitoring health
```

Redact secrets. Do not print full environment files, tokens, passwords, private keys or database connection strings.

## 3. Collision and dependency analysis

Before installation, identify:

- port conflicts;
- network/subnet conflicts;
- container/project-name conflicts;
- shared PostgreSQL/Redis/OpenBao dependencies;
- existing MoneyBee containers or stale checkouts;
- public hostname conflicts;
- duplicate Caddy/Kong routes;
- database names, roles and schema ownership;
- insufficient disk/memory/headroom;
- incompatible container engine/runtime versions;
- unsupported live source drift.

Any durable correction must be committed in the owning repository. Do not edit an authoritative server file without an equivalent reviewed repository change and release-lock update.

## 4. Backups

Before any MoneyBee mutation, create timestamped, checksummed backups for every affected stateful component:

- MoneyBee PostgreSQL database or the complete database cluster scope needed for restore;
- existing MoneyBee Redis state when durability is required;
- existing MoneyBee object/document data if present;
- Caddy, Kong and Keycloak configuration/state affected by the change;
- OpenBao/Vault configuration and sealed backup procedure according to its operating model;
- MoneyBee runtime manifests, environment-file metadata, volume maps and service definitions;
- Odoo/n8n/Middleware configuration only when the phase will change them;
- current production image/runtime lock and previous release artifacts.

Requirements:

- encrypt backup data at rest;
- store at least one copy outside the affected runtime path;
- restrict permissions;
- calculate SHA-256 checksums;
- record start/end UTC timestamps and size;
- do not include plaintext secrets in evidence;
- record retention and deletion policy.

## 5. Isolated restore proof

A backup is not `PASS` until restored into an isolated environment that cannot affect production.

Prove at minimum:

```text
backup decrypts and checksum matches
PostgreSQL restore completes
Alembic version can be read
required tables and row-count sanity checks pass
referential integrity checks pass
application can connect using a disposable nonproduction role
no production DNS/provider endpoint is reachable from the restore test
restore evidence is retained
RTO and RPO are measured and recorded
```

For configuration backups, render or validate the restored configuration without applying it to production.

## 6. PostgreSQL authority separation

Create or verify distinct authorities:

```text
moneybee_migrator
  - owns or has the minimum DDL required by Alembic
  - used only by the one-shot migration job
  - not available to API or worker containers

moneybee_app
  - minimum DML on required application objects
  - no CREATE/ALTER/DROP
  - no database/schema ownership
  - no superuser, CREATEROLE, CREATEDB, replication or bypass-RLS
  - used by API and workers

backup/restore role
  - minimum approved backup rights
  - not used by application runtime
```

Test runtime DDL denial with harmless transactional probes and rollback. Do not grant broad rights merely to pass startup.

## 7. Runtime directories and permissions

Prepare a release-oriented layout without placing mutable source code in the runtime path, for example:

```text
/opt/moneybee/releases/<release-id>/
/opt/moneybee/current -> releases/<release-id>
/opt/moneybee/shared/config/
/opt/moneybee/shared/secrets/
/opt/moneybee/shared/data/
/opt/moneybee/backups/
/opt/moneybee/evidence/<release-id>/
```

Use the existing server standard when one is already documented. Runtime manifests are read-only to the service where possible. Secrets are root/approved-service readable only. Container services run unprivileged where supported.

## 8. Baseline rollback checkpoint

Before installation, record:

- all affected running container IDs/image digests;
- current configuration checksums;
- current database schema version;
- backup/restore artifact references;
- current DNS/TLS/ingress state;
- exact commands needed to restore the previous state;
- rollback decision owner.

## Exit gate

Phase 03 is `GO` only when:

```text
RELEASE_LOCK_VERIFIED=PASS
READ_ONLY_INVENTORY_COMPLETE=YES
PORT_AND_NETWORK_COLLISIONS_RESOLVED=YES
CAPACITY=PASS
BACKUP=PASS
OFF_PATH_BACKUP_COPY=PASS
ISOLATED_RESTORE=PASS
DATABASE_ROLE_SEPARATION=PASS
RUNTIME_DDL_DENIAL=PASS
BASELINE_ROLLBACK_CHECKPOINT=PASS
SECRETS_REDACTED_FROM_EVIDENCE=PASS
```

If any item fails, report `PHASE_03_NO_GO`. Continue safe diagnosis and repository remediation, but do not install or migrate MoneyBee.
