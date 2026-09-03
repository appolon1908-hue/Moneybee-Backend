#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${TARGET_HOST:?TARGET_HOST is required}"
: "${SSH_USER:?SSH_USER is required}"
: "${KNOWN_HOSTS_FILE:?KNOWN_HOSTS_FILE is required}"
: "${EVIDENCE_DIR:?EVIDENCE_DIR is required}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
python "$SCRIPT_DIR/validate-source-authority.py" \
  --source-lock "$REPO_ROOT/deploy/repository-source.lock.json" \
  --operation server-contact

[[ "$TARGET_HOST" == "49.12.145.107" ]] || {
  echo "ERROR=UNAPPROVED_TARGET_HOST" >&2
  exit 1
}
[[ -s "$KNOWN_HOSTS_FILE" ]] || {
  echo "ERROR=KNOWN_HOSTS_FILE_MISSING" >&2
  exit 1
}

PROPOSED_RELEASE_ROOT="${PROPOSED_RELEASE_ROOT:-/opt/moneybee/releases}"
PROPOSED_CURRENT_SYMLINK="${PROPOSED_CURRENT_SYMLINK:-/opt/moneybee/current}"
PROPOSED_BACKEND_ENV_FILE="${PROPOSED_BACKEND_ENV_FILE:-/etc/moneybee/backend.env}"
PROPOSED_POSTGRES_DATA_PATH="${PROPOSED_POSTGRES_DATA_PATH:-/var/lib/moneybee/postgres}"
PROPOSED_REDIS_DATA_PATH="${PROPOSED_REDIS_DATA_PATH:-/var/lib/moneybee/redis}"
PROPOSED_POSTGRES_PASSWORD_FILE="${PROPOSED_POSTGRES_PASSWORD_FILE:-/etc/moneybee/secrets/postgres_password}"
PROPOSED_REDIS_ACL_FILE="${PROPOSED_REDIS_ACL_FILE:-/etc/moneybee/secrets/redis.acl}"
PROPOSED_CADDY_DATA_PATH="${PROPOSED_CADDY_DATA_PATH:-/var/lib/moneybee/caddy/data}"
PROPOSED_CADDY_CONFIG_PATH="${PROPOSED_CADDY_CONFIG_PATH:-/var/lib/moneybee/caddy/config}"
PROPOSED_BACKUP_ROOT="${PROPOSED_BACKUP_ROOT:-/var/backups/moneybee}"

mkdir -p "$EVIDENCE_DIR"
raw="$EVIDENCE_DIR/runtime-preflight.raw.txt"

ssh \
  -T \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
  -o ConnectTimeout=12 \
  "$SSH_USER@$TARGET_HOST" \
  bash -s -- \
  "$PROPOSED_RELEASE_ROOT" \
  "$PROPOSED_CURRENT_SYMLINK" \
  "$PROPOSED_BACKEND_ENV_FILE" \
  "$PROPOSED_POSTGRES_DATA_PATH" \
  "$PROPOSED_REDIS_DATA_PATH" \
  "$PROPOSED_POSTGRES_PASSWORD_FILE" \
  "$PROPOSED_REDIS_ACL_FILE" \
  "$PROPOSED_CADDY_DATA_PATH" \
  "$PROPOSED_CADDY_CONFIG_PATH" \
  "$PROPOSED_BACKUP_ROOT" >"$raw" <<'REMOTE'
set -u

path_report() {
  key="$1"
  path="$2"
  printf 'path.%s.requested=%s\n' "$key" "$path"
  if [ -e "$path" ] || [ -L "$path" ]; then
    printf 'path.%s.exists=true\n' "$key"
    printf 'path.%s.real=%s\n' "$key" "$(readlink -f "$path" 2>/dev/null || printf '%s' "$path")"
    stat -Lc "path.$key.mode=%a path.$key.uid=%u path.$key.gid=%g path.$key.type=%F" "$path" 2>/dev/null || true
  else
    printf 'path.%s.exists=false\n' "$key"
    parent="$(dirname "$path")"
    printf 'path.%s.parent=%s\n' "$key" "$parent"
    if [ -e "$parent" ]; then
      stat -Lc "path.$key.parent_mode=%a path.$key.parent_uid=%u path.$key.parent_gid=%g path.$key.parent_type=%F" "$parent" 2>/dev/null || true
      df -Pk "$parent" 2>/dev/null | tail -1 | awk -v key="$key" '{print "path." key ".parent_df=" $0}'
    else
      printf 'path.%s.parent_exists=false\n' "$key"
    fi
  fi
}

printf 'captured_at_utc=%s\n' "$(date -u +%FT%TZ)"
printf 'hostname=%s\n' "$(hostname 2>/dev/null || true)"
printf 'hostname_fqdn=%s\n' "$(hostname -f 2>/dev/null || true)"
printf 'hostname_ips=%s\n' "$(hostname -I 2>/dev/null | xargs || true)"
printf 'kernel=%s\n' "$(uname -srmo 2>/dev/null || true)"
if [ -r /etc/os-release ]; then
  sed 's/^/os_release./' /etc/os-release
fi
printf 'effective_user=%s\n' "$(id -un 2>/dev/null || true)"
printf 'effective_uid=%s\n' "$(id -u 2>/dev/null || true)"

if command -v docker >/dev/null 2>&1; then
  printf 'docker.path=%s\n' "$(command -v docker)"
  printf 'docker.version=%s\n' "$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
  printf 'docker.compose_version=%s\n' "$(docker compose version --short 2>/dev/null || true)"
  printf '%s\n' 'docker.containers.begin'
  docker ps -a --format '{{json .}}' 2>/dev/null || true
  printf '%s\n' 'docker.containers.end'
  printf '%s\n' 'docker.networks.begin'
  docker network ls --format '{{json .}}' 2>/dev/null || true
  printf '%s\n' 'docker.networks.end'
  printf '%s\n' 'docker.volumes.begin'
  docker volume ls --format '{{json .}}' 2>/dev/null || true
  printf '%s\n' 'docker.volumes.end'
else
  printf 'docker.path=MISSING\n'
fi

printf '%s\n' 'listeners.begin'
ss -H -lntup 2>/dev/null || true
printf '%s\n' 'listeners.end'

for service in docker caddy nginx apache2 postgresql redis-server; do
  printf 'service.%s=%s\n' "$service" "$(systemctl is-active "$service" 2>/dev/null || true)"
done

path_report release_root "$1"
path_report current_symlink "$2"
path_report backend_env_file "$3"
path_report postgres_data_path "$4"
path_report redis_data_path "$5"
path_report postgres_password_file "$6"
path_report redis_acl_file "$7"
path_report caddy_data_path "$8"
path_report caddy_config_path "$9"
path_report backup_root "${10}"

printf '%s\n' 'mounts.begin'
findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null || true
printf '%s\n' 'mounts.end'
REMOTE

RAW_EVIDENCE="$raw" \
EVIDENCE_DIR="$EVIDENCE_DIR" \
TARGET_HOST="$TARGET_HOST" \
SSH_USER="$SSH_USER" \
PROPOSED_RELEASE_ROOT="$PROPOSED_RELEASE_ROOT" \
PROPOSED_CURRENT_SYMLINK="$PROPOSED_CURRENT_SYMLINK" \
PROPOSED_BACKEND_ENV_FILE="$PROPOSED_BACKEND_ENV_FILE" \
PROPOSED_POSTGRES_DATA_PATH="$PROPOSED_POSTGRES_DATA_PATH" \
PROPOSED_REDIS_DATA_PATH="$PROPOSED_REDIS_DATA_PATH" \
PROPOSED_POSTGRES_PASSWORD_FILE="$PROPOSED_POSTGRES_PASSWORD_FILE" \
PROPOSED_REDIS_ACL_FILE="$PROPOSED_REDIS_ACL_FILE" \
PROPOSED_CADDY_DATA_PATH="$PROPOSED_CADDY_DATA_PATH" \
PROPOSED_CADDY_CONFIG_PATH="$PROPOSED_CADDY_CONFIG_PATH" \
PROPOSED_BACKUP_ROOT="$PROPOSED_BACKUP_ROOT" \
python - <<'PY'
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

raw = Path(os.environ["RAW_EVIDENCE"])
raw_text = raw.read_text(encoding="utf-8", errors="replace")
digest = hashlib.sha256(raw.read_bytes()).hexdigest()
observed = {}
for line in raw_text.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        if key in {"hostname", "hostname_fqdn", "hostname_ips"}:
            observed[key] = value
candidate = {
    "schema_version": 1,
    "status": "CANDIDATE_ONLY",
    "target_host": os.environ["TARGET_HOST"],
    "ssh_user": os.environ["SSH_USER"],
    "captured_at": datetime.now(UTC).isoformat(),
    "raw_evidence_file": raw.name,
    "raw_evidence_sha256": digest,
    "live_changes": False,
    "observed_identity": observed,
    "proposed_paths": {
        "release_root": os.environ["PROPOSED_RELEASE_ROOT"],
        "current_symlink": os.environ["PROPOSED_CURRENT_SYMLINK"],
        "backend_env_file": os.environ["PROPOSED_BACKEND_ENV_FILE"],
        "postgres_data_path": os.environ["PROPOSED_POSTGRES_DATA_PATH"],
        "redis_data_path": os.environ["PROPOSED_REDIS_DATA_PATH"],
        "postgres_password_file": os.environ["PROPOSED_POSTGRES_PASSWORD_FILE"],
        "redis_acl_file": os.environ["PROPOSED_REDIS_ACL_FILE"],
        "caddy_data_path": os.environ["PROPOSED_CADDY_DATA_PATH"],
        "caddy_config_path": os.environ["PROPOSED_CADDY_CONFIG_PATH"],
        "backup_root": os.environ["PROPOSED_BACKUP_ROOT"],
    },
    "review_required": True,
}
out = Path(os.environ["EVIDENCE_DIR"]) / "runtime-paths.candidate.json"
out.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
print(f"RAW_EVIDENCE_SHA256={digest}")
print(f"CANDIDATE={out}")
PY
