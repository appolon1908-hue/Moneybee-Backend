#!/usr/bin/env bash
set -Eeuo pipefail

cat >&2 <<'EOF'
ERROR=REMOTE_DEPLOYMENT_BLOCKED
The MoneyBee staging deployment executor is intentionally not implemented in this
scaffold. Review and commit VERIFIED runtime-path and release locks first, then add a
separately reviewed deployment executor bound to those exact evidence records.
No server operation was performed.
EOF
exit 1
