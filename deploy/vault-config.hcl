# Minimal single-node Vault server config for the bank-credential-store
# profile (see deploy/compose.data.yml). File storage backend - no external
# HA dependency, matching this project's single-host deployment target.
# TLS is disabled because Vault only ever listens on moneybee_internal, the
# same docker-only bridge network Postgres and Redis already communicate
# over unencrypted - it is never published to the host or reachable from
# moneybee_edge/the public internet.
#
# This file describes server *configuration*, not a running, initialized,
# unsealed Vault. A fresh Vault started from this config is sealed and
# empty - `vault operator init` and `vault operator unseal` are one-time
# operator actions this repo cannot and does not perform (see deploy/README.md).

storage "file" {
  path = "/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

disable_mlock = false
ui            = false
