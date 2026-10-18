#!/usr/bin/env bash
# Deterministically reset demo state to the synthetic seed.
# If the backend is running, reset via the API; otherwise reseed MongoDB directly (needs MONGODB_URI).
# Usage: scripts/reset_demo.sh [core|full]   (default: DEMO_DATASET, else core; cast in docs/demo-cast.md)
set -euo pipefail
DATASET="${1:-${DEMO_DATASET:-}}"
case "$DATASET" in ""|core|full) ;; *) echo "dataset must be core or full"; exit 2;; esac
source "$(dirname "$0")/_env.sh"
API="${DOORSTEP_API_URL:-http://127.0.0.1:$DOORSTEP_API_PORT}"
if curl -fsS "$API/health" >/dev/null 2>&1; then
  BODY=$([ -n "$DATASET" ] && echo "{\"dataset\": \"$DATASET\"}" || echo "{}")
  curl -fsS -X POST "$API/demo/reset" -H "Authorization: Bearer $DEMO_AUTH_TOKEN" \
       -H "content-type: application/json" -d "$BODY"
  echo
  echo "Reset via running backend at $API"
elif [ "${USE_MONGOMOCK:-false}" = "true" ]; then
  echo "Backend not running and no MONGODB_URI set: in-memory data starts fresh on next start (auto-seeded)."
else
  DATASET="$DATASET" "$PY" - <<'PY'
import os
from doorstep.services.db import Database
from doorstep.services.engine import DoorstepService
print(DoorstepService(Database()).reset(os.environ.get("DATASET") or None))
PY
  echo "Reseeded $MONGODB_URI ($MONGODB_USERS_DB + $MONGODB_PARTNERS_DB)"
fi
