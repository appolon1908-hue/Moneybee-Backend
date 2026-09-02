# Current MoneyBee production deployment baseline

Captured: 2026-09-01 UTC. Secret values are excluded.

## Source and deployment identity

- Deployed backend source commit: `07dda9c6c9b09c00d1c91ba545a5ef9bfc804dd3`
- Deployed release suffix: `476b135213a3-07dda9c6c9b0`
- Audited repository: `appolon1908-hue/Moneybee-Backend`
- Repository production branch at capture: `89fdc6e409bf1eb196cac66c709ba21a338afba2`
- Repository main branch at capture: `cc7b1716eba643a96a3647e0352b79f0c1738263`
- Selected hardening baseline: `ff3a688b705450f9e2f33a88ad08e16b0c9f6143`
- Production is materially behind the selected hardening source. It must not be described as source-aligned until a reviewed immutable release is built and deployed.

## Running images

| Container | Image tag | Local immutable image digest |
|---|---|---|
| moneybee-api | `moneybee-api:476b135213a3-07dda9c6c9b0` | `sha256:a51f6dba04b4a002c329e85271e0d5f05b4f788f8ac6b74e32881ce76b14d5df` |
| moneybee-marketing | `moneybee-marketing:476b135213a3-07dda9c6c9b0` | `sha256:bd68446f333644eeecf15f68d53c49b717a292091704d809f3a12ae34be99c12` |
| moneybee-borrower | `moneybee-borrower:476b135213a3-07dda9c6c9b0` | `sha256:a1507c569a7e452a96068b9a010e45b9630856b40aaacd05136dfab15c15ced7` |
| moneybee-lender | `moneybee-lender:476b135213a3-07dda9c6c9b0` | `sha256:b43960d30d7ad1191ffac1cbdd4dda76f544ab60e424f4edda6538cdcc518d7d` |
| moneybee-admin | `moneybee-admin:476b135213a3-07dda9c6c9b0` | `sha256:5e0525261d0440d77218920654fe8bb2c397d913941aacb3bde9d04649d4bdc7` |

The images are locally content-addressed, but the deployment is not backed by a recorded registry digest/SBOM/CI run chain for this release.

## Database and cache

- PostgreSQL: 17.10
- Production database: `moneybee`
- Current application/bootstrap role: `moneybee` (SUPERUSER; remediation required)
- Current Alembic revision: `20260827_0016`
- Redis: 7.4.10
- Redis persistence: AOF enabled with `appendfsync=everysec`, RDB `save 60 1`

## Compose source

- File: `/opt/moneybee/frontend/deploy/docker-compose.production.yml`
- SHA-256: `cb0900def2b50178049a1b90626eb33458469ef4287789e8120abdf23dbc1f87`
- Last modified: 2026-08-27 11:30:39 UTC

## Rollback baseline

The five current application images and their exact local digests above are the pre-change rollback set. The current Compose and secret files must be copied into the restricted change-evidence directory before deployment. Database rollback must use the verified pre-change backup/PITR recovery point; application rollback alone is not safe after an incompatible migration.
