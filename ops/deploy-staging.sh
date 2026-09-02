#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: ops/deploy-staging.sh [--execute] [--external-data]
                             [--runtime-lock PATH] [--release-lock PATH]

Validates the exact reviewed staging release and prints the deployment plan.
The default is dry-run. --execute performs the plan only after both locks pass
their fail-closed VERIFIED checks. This executor supports staging only.
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_dir="$(cd -- "$script_dir/.." && pwd -P)"
python_bin="${MONEYBEE_PYTHON_BIN:-python3}"
runtime_lock="$repo_dir/deploy/runtime-paths.lock.json"
release_lock="$repo_dir/deploy/release.lock.json"
execute=0
external_data=0

while (($#)); do
  case "$1" in
    --execute) execute=1 ;;
    --external-data) external_data=1 ;;
    --runtime-lock)
      (($# >= 2)) || { echo "ERROR=--runtime-lock requires a path" >&2; exit 2; }
      runtime_lock="$2"; shift ;;
    --release-lock)
      (($# >= 2)) || { echo "ERROR=--release-lock requires a path" >&2; exit 2; }
      release_lock="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR=unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

command -v "$python_bin" >/dev/null || {
  echo "ERROR=Python interpreter not found: $python_bin" >&2
  exit 1
}

"$python_bin" "$script_dir/validate-release-lock.py" \
  --runtime-lock "$runtime_lock" --release-lock "$release_lock"

rendered_env="$(mktemp)"
cleanup() { rm -f -- "$rendered_env"; }
trap cleanup EXIT
chmod 600 "$rendered_env"
"$python_bin" "$script_dir/render-compose-env.py" \
  --runtime-lock "$runtime_lock" --release-lock "$release_lock" >"$rendered_env"

# shellcheck disable=SC1090 -- generated exclusively by the reviewed renderer
set -a; source "$rendered_env"; set +a

compose=(-f "$repo_dir/deploy/compose.backend.yml" -f "$repo_dir/deploy/compose.edge.yml")
if ((external_data == 0)); then
  compose=(-f "$repo_dir/deploy/compose.data.yml" "${compose[@]}")
fi

docker compose "${compose[@]}" config --quiet
printf '%s\n' \
  "TARGET_ENVIRONMENT=staging" \
  "LOCK_VALIDATION=PASS" \
  "COMPOSE_VALIDATION=PASS" \
  "EXTERNAL_DATA=$external_data" \
  "CAPABILITIES_ENABLED=NONE"

if ((execute == 0)); then
  echo "DEPLOYMENT=DRY_RUN"
  exit 0
fi

test "${MONEYBEE_DEPLOY_CONFIRMATION:-}" = "DEPLOY-VERIFIED-STAGING" || {
  echo "ERROR=MONEYBEE_DEPLOY_CONFIRMATION must equal DEPLOY-VERIFIED-STAGING" >&2
  exit 1
}

docker compose "${compose[@]}" pull
if ((external_data == 0)); then
  docker compose "${compose[@]}" --profile bootstrap run --rm role-bootstrap
fi
docker compose "${compose[@]}" --profile migrate run --rm migrate
docker compose "${compose[@]}" up -d --remove-orphans
docker compose "${compose[@]}" ps
echo "DEPLOYMENT=EXECUTED"
