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
PROPOSED_MIGRATOR_ENV_FILE="${PROPOSED_MIGRATOR_ENV_FILE:-/etc/moneybee/migrator.env}"
PROPOSED_RUNTIME_ENV_FILE="${PROPOSED_RUNTIME_ENV_FILE:-/etc/moneybee/runtime.env}"
PROPOSED_ROLES_SQL_PATH="${PROPOSED_ROLES_SQL_PATH:-/etc/moneybee/bootstrap/roles.sql}"
PROPOSED_POSTGRES_DATA_PATH="${PROPOSED_POSTGRES_DATA_PATH:-/var/lib/moneybee/postgres}"
PROPOSED_REDIS_DATA_PATH="${PROPOSED_REDIS_DATA_PATH:-/var/lib/moneybee/redis}"
PROPOSED_POSTGRES_ADMIN_PASSWORD_FILE="${PROPOSED_POSTGRES_ADMIN_PASSWORD_FILE:-/etc/moneybee/secrets/postgres_admin_password}"
PROPOSED_POSTGRES_MIGRATOR_PASSWORD_FILE="${PROPOSED_POSTGRES_MIGRATOR_PASSWORD_FILE:-/etc/moneybee/secrets/postgres_migrator_password}"
PROPOSED_POSTGRES_RUNTIME_PASSWORD_FILE="${PROPOSED_POSTGRES_RUNTIME_PASSWORD_FILE:-/etc/moneybee/secrets/postgres_runtime_password}"
PROPOSED_REDIS_ACL_FILE="${PROPOSED_REDIS_ACL_FILE:-/etc/moneybee/secrets/redis.acl}"
PROPOSED_CLAMAV_DATABASE_PATH="${PROPOSED_CLAMAV_DATABASE_PATH:-/var/lib/moneybee/clamav}"
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
  "$PROPOSED_MIGRATOR_ENV_FILE" \
  "$PROPOSED_RUNTIME_ENV_FILE" \
  "$PROPOSED_ROLES_SQL_PATH" \
  "$PROPOSED_POSTGRES_DATA_PATH" \
  "$PROPOSED_REDIS_DATA_PATH" \
  "$PROPOSED_POSTGRES_ADMIN_PASSWORD_FILE" \
  "$PROPOSED_POSTGRES_MIGRATOR_PASSWORD_FILE" \
  "$PROPOSED_POSTGRES_RUNTIME_PASSWORD_FILE" \
  "$PROPOSED_REDIS_ACL_FILE" \
  "$PROPOSED_CLAMAV_DATABASE_PATH" \
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
    if [ -d "$path" ]; then
      df -Pk "$path" 2>/dev/null | tail -1 | awk -v key="$key" '{print "path." key ".df=" $0}'
      df -Pik "$path" 2>/dev/null | tail -1 | awk -v key="$key" '{print "path." key ".inode_df=" $0}'
    fi
  else
    printf 'path.%s.exists=false\n' "$key"
    parent="$(dirname "$path")"
    printf 'path.%s.parent=%s\n' "$key" "$parent"
    if [ -e "$parent" ]; then
      stat -Lc "path.$key.parent_mode=%a path.$key.parent_uid=%u path.$key.parent_gid=%g path.$key.parent_type=%F" "$parent" 2>/dev/null || true
      df -Pk "$parent" 2>/dev/null | tail -1 | awk -v key="$key" '{print "path." key ".parent_df=" $0}'
      df -Pik "$parent" 2>/dev/null | tail -1 | awk -v key="$key" '{print "path." key ".parent_inode_df=" $0}'
    else
      printf 'path.%s.parent_exists=false\n' "$key"
    fi
  fi
}

section() {
  printf '%s.begin\n' "$1"
  cat
  printf '%s.end\n' "$1"
}

printf 'captured_at_utc=%s\n' "$(date -u +%FT%TZ)"
printf 'hostname=%s\n' "$(hostname 2>/dev/null || true)"
printf 'hostname_fqdn=%s\n' "$(hostname -f 2>/dev/null || true)"
printf 'hostname_ips=%s\n' "$(hostname -I 2>/dev/null | xargs || true)"
printf 'kernel=%s\n' "$(uname -srmo 2>/dev/null || true)"
printf 'effective_user=%s\n' "$(id -un 2>/dev/null || true)"
printf 'effective_uid=%s\n' "$(id -u 2>/dev/null || true)"
printf 'cpu_count=%s\n' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || true)"
printf 'load_average=%s\n' "$(cat /proc/loadavg 2>/dev/null || true)"
printf 'uptime_seconds=%s\n' "$(cut -d. -f1 /proc/uptime 2>/dev/null || true)"
if [ -r /etc/os-release ]; then
  sed 's/^/os_release./' /etc/os-release
fi

{
  free -b 2>/dev/null || true
} | section memory
{
  df -PTk 2>/dev/null || true
} | section filesystems
{
  df -PTik 2>/dev/null || true
} | section inodes
{
  findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null || true
} | section mounts

if command -v docker >/dev/null 2>&1; then
  printf 'docker.path=%s\n' "$(command -v docker)"
  printf 'docker.version=%s\n' "$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
  printf 'docker.compose_version=%s\n' "$(docker compose version --short 2>/dev/null || true)"
  if docker info >/dev/null 2>&1; then
    printf 'docker.available=true\n'
    printf 'docker.container_count=%s\n' "$(docker ps -aq 2>/dev/null | wc -l | xargs)"

    printf '%s\n' 'docker.containers.begin'
    if command -v jq >/dev/null 2>&1; then
      while IFS= read -r container_id; do
        [ -n "$container_id" ] || continue
        container_json="$(
          docker inspect "$container_id" 2>/dev/null | jq -c '.[0] | {
            id: .Id,
            name: (.Name | ltrimstr("/")),
            image_ref: .Config.Image,
            image_id: .Image,
            created: .Created,
            state: .State.Status,
            running: .State.Running,
            health: (.State.Health.Status // null),
            started_at: .State.StartedAt,
            finished_at: .State.FinishedAt,
            exit_code: .State.ExitCode,
            restart_policy: .HostConfig.RestartPolicy.Name,
            privileged: .HostConfig.Privileged,
            readonly_rootfs: .HostConfig.ReadonlyRootfs,
            user: .Config.User,
            compose_project: (.Config.Labels["com.docker.compose.project"] // null),
            compose_service: (.Config.Labels["com.docker.compose.service"] // null),
            mounts: [.Mounts[]? | {
              type: .Type,
              source: .Source,
              destination: .Destination,
              mode: .Mode,
              rw: .RW
            }],
            networks: (.NetworkSettings.Networks | keys),
            ports: (.NetworkSettings.Ports // {})
          }' || true
        )"
        [ -n "$container_json" ] || continue
        image_id="$(printf '%s' "$container_json" | jq -r '.image_id')"
        repo_digests="$(docker image inspect "$image_id" 2>/dev/null | jq -c '.[0].RepoDigests // []' || printf '[]')"
        printf '%s\n' "$container_json" | jq -c --argjson repo_digests "$repo_digests" '. + {repo_digests: $repo_digests}'
      done < <(docker ps -aq 2>/dev/null)
    else
      docker ps -a --no-trunc --format '{{json .}}' 2>/dev/null || true
    fi
    printf '%s\n' 'docker.containers.end'

    printf '%s\n' 'docker.images.begin'
    docker image ls --digests --no-trunc --format '{{json .}}' 2>/dev/null || true
    printf '%s\n' 'docker.images.end'

    printf '%s\n' 'docker.compose_projects.begin'
    docker compose ls --all --format json 2>/dev/null || true
    printf '%s\n' 'docker.compose_projects.end'

    printf '%s\n' 'docker.networks.begin'
    docker network ls --format '{{json .}}' 2>/dev/null || true
    printf '%s\n' 'docker.networks.end'

    printf '%s\n' 'docker.volumes.begin'
    docker volume ls --format '{{json .}}' 2>/dev/null || true
    printf '%s\n' 'docker.volumes.end'
  else
    printf 'docker.available=false\n'
  fi
else
  printf 'docker.path=MISSING\n'
  printf 'docker.available=false\n'
fi

{
  ss -H -lntup 2>/dev/null || true
} | section listeners

{
  systemctl list-units --type=service --all --no-pager --no-legend 2>/dev/null | grep -Ei 'docker|containerd|caddy|nginx|apache|postgres|redis|moneybee|keycloak|kong|openbao|vault|odoo|n8n|prometheus|grafana' || true
} | section relevant_services

{
  systemctl list-timers --all --no-pager --no-legend 2>/dev/null | grep -Ei 'backup|moneybee|postgres|redis|docker|cert|renew' || true
} | section relevant_timers

{
  if command -v ufw >/dev/null 2>&1; then ufw status verbose 2>/dev/null || true; fi
  if command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --list-all 2>/dev/null || true; fi
} | section firewall_summary

for key_path in \
  "release_root:$1" \
  "current_symlink:$2" \
  "migrator_env_file:$3" \
  "runtime_env_file:$4" \
  "roles_sql_path:$5" \
  "postgres_data_path:$6" \
  "redis_data_path:$7" \
  "postgres_admin_password_file:$8" \
  "postgres_migrator_password_file:$9" \
  "postgres_runtime_password_file:${10}" \
  "redis_acl_file:${11}" \
  "clamav_database_path:${12}" \
  "caddy_data_path:${13}" \
  "caddy_config_path:${14}" \
  "backup_root:${15}"; do
  path_report "${key_path%%:*}" "${key_path#*:}"
done

{
  current="$2"
  if [ -e "$current" ] || [ -L "$current" ]; then
    real_current="$(readlink -f "$current" 2>/dev/null || printf '%s' "$current")"
    find "$real_current" -maxdepth 4 -type f \
      \( -name '*.yml' -o -name '*.yaml' -o -name '*.json' -o -name 'Caddyfile*' -o -name '*.conf' \) \
      ! -name '*.env' ! -path '*/secrets/*' -print0 2>/dev/null |
      sort -z |
      xargs -0 -r sha256sum 2>/dev/null || true
  fi
} | section current_config_checksums

{
  backup_root="${15}"
  if [ -d "$backup_root" ]; then
    find "$backup_root" -maxdepth 3 -type f -printf '%TY-%Tm-%TdT%TH:%TM:%TSZ %s %m %u:%g %p\n' 2>/dev/null | sort -r | head -200
  fi
} | section backup_metadata

{
  for root in /opt /srv /var/www; do
    [ -d "$root" ] || continue
    find "$root" -xdev -maxdepth 5 -type d -name .git -printf '%h\n' 2>/dev/null || true
  done
} | section git_checkouts

{
  for domain in \
    moneybeeloan.com \
    www.moneybeeloan.com \
    app.moneybeeloan.com \
    lenders.moneybeeloan.com \
    admin.moneybeeloan.com \
    api.moneybeeloan.com \
    auth.codestra.co; do
    printf 'domain=%s\n' "$domain"
    getent ahosts "$domain" 2>/dev/null | awk '{print "address=" $1}' | sort -u || true
    if command -v openssl >/dev/null 2>&1; then
      timeout 10 openssl s_client -servername "$domain" -connect "$domain:443" </dev/null 2>/dev/null |
        openssl x509 -noout -subject -issuer -dates -fingerprint -sha256 2>/dev/null || true
    fi
  done
} | section dns_tls
REMOTE

RAW_EVIDENCE="$raw" \
EVIDENCE_DIR="$EVIDENCE_DIR" \
TARGET_HOST="$TARGET_HOST" \
SSH_USER="$SSH_USER" \
PROPOSED_RELEASE_ROOT="$PROPOSED_RELEASE_ROOT" \
PROPOSED_CURRENT_SYMLINK="$PROPOSED_CURRENT_SYMLINK" \
PROPOSED_MIGRATOR_ENV_FILE="$PROPOSED_MIGRATOR_ENV_FILE" \
PROPOSED_RUNTIME_ENV_FILE="$PROPOSED_RUNTIME_ENV_FILE" \
PROPOSED_ROLES_SQL_PATH="$PROPOSED_ROLES_SQL_PATH" \
PROPOSED_POSTGRES_DATA_PATH="$PROPOSED_POSTGRES_DATA_PATH" \
PROPOSED_REDIS_DATA_PATH="$PROPOSED_REDIS_DATA_PATH" \
PROPOSED_POSTGRES_ADMIN_PASSWORD_FILE="$PROPOSED_POSTGRES_ADMIN_PASSWORD_FILE" \
PROPOSED_POSTGRES_MIGRATOR_PASSWORD_FILE="$PROPOSED_POSTGRES_MIGRATOR_PASSWORD_FILE" \
PROPOSED_POSTGRES_RUNTIME_PASSWORD_FILE="$PROPOSED_POSTGRES_RUNTIME_PASSWORD_FILE" \
PROPOSED_REDIS_ACL_FILE="$PROPOSED_REDIS_ACL_FILE" \
PROPOSED_CLAMAV_DATABASE_PATH="$PROPOSED_CLAMAV_DATABASE_PATH" \
PROPOSED_CADDY_DATA_PATH="$PROPOSED_CADDY_DATA_PATH" \
PROPOSED_CADDY_CONFIG_PATH="$PROPOSED_CADDY_CONFIG_PATH" \
PROPOSED_BACKUP_ROOT="$PROPOSED_BACKUP_ROOT" \
python - <<'PY'
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

raw = Path(os.environ["RAW_EVIDENCE"])
raw_text = raw.read_text(encoding="utf-8", errors="replace")
raw_digest = hashlib.sha256(raw.read_bytes()).hexdigest()
lines = raw_text.splitlines()

sections: dict[str, list[str]] = {}
scalars: dict[str, str] = {}
active: str | None = None
for line in lines:
    if line.endswith(".begin"):
        active = line[:-6]
        sections.setdefault(active, [])
        continue
    if line.endswith(".end") and active == line[:-4]:
        active = None
        continue
    if active is not None:
        sections[active].append(line)
    elif "=" in line:
        key, value = line.split("=", 1)
        scalars[key] = value


def parse_json_lines(name: str) -> list[Any]:
    values: list[Any] = []
    for line in sections.get(name, []):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            values.extend(value)
        else:
            values.append(value)
    return values

containers = [value for value in parse_json_lines("docker.containers") if isinstance(value, dict)]
images = [value for value in parse_json_lines("docker.images") if isinstance(value, dict)]
compose_projects = parse_json_lines("docker.compose_projects")
networks = [value for value in parse_json_lines("docker.networks") if isinstance(value, dict)]
volumes = [value for value in parse_json_lines("docker.volumes") if isinstance(value, dict)]

moneybee_containers = []
for container in containers:
    haystack = " ".join(
        str(container.get(key) or "").lower()
        for key in ("name", "image_ref", "compose_project", "compose_service")
    )
    if "moneybee" in haystack:
        moneybee_containers.append(container)

roles = {
    "api": ("moneybee-api",),
    "worker": ("moneybee-worker",),
    "migrate": ("moneybee-migrate",),
    "marketing": ("moneybee-marketing",),
    "borrower": ("moneybee-borrower",),
    "lender": ("moneybee-lender",),
    "admin": ("moneybee-admin",),
    "postgres": ("moneybee-postgres", "postgres"),
    "redis": ("moneybee-redis", "redis"),
    "caddy": ("moneybee-caddy", "caddy"),
    "clamav": ("moneybee-clamav", "clamav", "clamd"),
}
rollback_candidates: dict[str, Any] = {}
for role, needles in roles.items():
    selected = None
    for container in moneybee_containers:
        haystack = " ".join(
            str(container.get(key) or "").lower()
            for key in ("name", "image_ref", "compose_service")
        )
        if any(needle in haystack for needle in needles):
            selected = container
            break
    if selected is None and role in {"postgres", "redis", "caddy", "clamav"}:
        for container in containers:
            haystack = " ".join(
                str(container.get(key) or "").lower()
                for key in ("name", "image_ref", "compose_service")
            )
            if any(needle in haystack for needle in needles):
                selected = container
                break
    if selected is not None:
        repo_digests = selected.get("repo_digests") or []
        immutable_identity = repo_digests[0] if repo_digests else selected.get("image_id")
        rollback_candidates[role] = {
            "container": selected.get("name"),
            "image_ref": selected.get("image_ref"),
            "image_id": selected.get("image_id"),
            "repo_digests": repo_digests,
            "immutable_identity": immutable_identity,
            "registry_redeployable": bool(repo_digests),
            "state": selected.get("state"),
            "health": selected.get("health"),
        }

observed_paths: dict[str, dict[str, str]] = {}
for key, value in scalars.items():
    if not key.startswith("path."):
        continue
    rest = key[5:]
    if "." not in rest:
        continue
    path_key, field = rest.split(".", 1)
    observed_paths.setdefault(path_key, {})[field] = value

proposed_paths = {
    "release_root": os.environ["PROPOSED_RELEASE_ROOT"],
    "current_symlink": os.environ["PROPOSED_CURRENT_SYMLINK"],
    "migrator_env_file": os.environ["PROPOSED_MIGRATOR_ENV_FILE"],
    "runtime_env_file": os.environ["PROPOSED_RUNTIME_ENV_FILE"],
    "roles_sql_path": os.environ["PROPOSED_ROLES_SQL_PATH"],
    "postgres_data_path": os.environ["PROPOSED_POSTGRES_DATA_PATH"],
    "redis_data_path": os.environ["PROPOSED_REDIS_DATA_PATH"],
    "postgres_admin_password_file": os.environ["PROPOSED_POSTGRES_ADMIN_PASSWORD_FILE"],
    "postgres_migrator_password_file": os.environ["PROPOSED_POSTGRES_MIGRATOR_PASSWORD_FILE"],
    "postgres_runtime_password_file": os.environ["PROPOSED_POSTGRES_RUNTIME_PASSWORD_FILE"],
    "redis_acl_file": os.environ["PROPOSED_REDIS_ACL_FILE"],
    "clamav_database_path": os.environ["PROPOSED_CLAMAV_DATABASE_PATH"],
    "caddy_data_path": os.environ["PROPOSED_CADDY_DATA_PATH"],
    "caddy_config_path": os.environ["PROPOSED_CADDY_CONFIG_PATH"],
    "backup_root": os.environ["PROPOSED_BACKUP_ROOT"],
}

inventory = {
    "schema_version": 1,
    "status": "READ_ONLY_CAPTURE_COMPLETE",
    "target_host": os.environ["TARGET_HOST"],
    "ssh_user": os.environ["SSH_USER"],
    "captured_at": datetime.now(UTC).isoformat(),
    "raw_evidence_file": raw.name,
    "raw_evidence_sha256": raw_digest,
    "live_changes": False,
    "host": {
        key: scalars.get(key)
        for key in (
            "hostname",
            "hostname_fqdn",
            "hostname_ips",
            "kernel",
            "effective_user",
            "effective_uid",
            "cpu_count",
            "load_average",
            "uptime_seconds",
        )
    },
    "docker": {
        "available": scalars.get("docker.available") == "true",
        "version": scalars.get("docker.version"),
        "compose_version": scalars.get("docker.compose_version"),
        "container_count": len(containers),
        "containers": containers,
        "images": images,
        "compose_projects": compose_projects,
        "networks": networks,
        "volumes": volumes,
    },
    "moneybee_containers": moneybee_containers,
    "rollback_candidates": rollback_candidates,
    "paths": observed_paths,
    "listeners": sections.get("listeners", []),
    "relevant_services": sections.get("relevant_services", []),
    "relevant_timers": sections.get("relevant_timers", []),
    "firewall_summary": sections.get("firewall_summary", []),
    "filesystems": sections.get("filesystems", []),
    "inodes": sections.get("inodes", []),
    "memory": sections.get("memory", []),
    "mounts": sections.get("mounts", []),
    "current_config_checksums": sections.get("current_config_checksums", []),
    "backup_metadata": sections.get("backup_metadata", []),
    "git_checkouts": sections.get("git_checkouts", []),
    "dns_tls": sections.get("dns_tls", []),
    "secrets_included": False,
}

candidate = {
    "schema_version": 1,
    "status": "CANDIDATE_ONLY",
    "target_host": os.environ["TARGET_HOST"],
    "ssh_user": os.environ["SSH_USER"],
    "captured_at": inventory["captured_at"],
    "raw_evidence_file": raw.name,
    "raw_evidence_sha256": raw_digest,
    "inventory_file": "runtime-inventory.json",
    "live_changes": False,
    "observed_identity": inventory["host"],
    "proposed_paths": proposed_paths,
    "observed_paths": observed_paths,
    "rollback_candidates": rollback_candidates,
    "review_required": True,
}

out_dir = Path(os.environ["EVIDENCE_DIR"])
(out_dir / "runtime-inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
(out_dir / "runtime-paths.candidate.json").write_text(
    json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"RAW_EVIDENCE_SHA256={raw_digest}")
print(f"MONEYBEE_CONTAINER_COUNT={len(moneybee_containers)}")
print(f"ROLLBACK_CANDIDATE_COUNT={len(rollback_candidates)}")
PY

(
  cd "$EVIDENCE_DIR"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' |
    sort |
    xargs sha256sum >SHA256SUMS
)
