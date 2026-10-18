#!/usr/bin/env bash
# Deterministically reset demo state to the synthetic seed.
# If the backend is running, reset via the API; otherwise reseed MongoDB directly (needs MONGODB_URI).
set -euo pipefail
source "$(dirname "$0")/_env.sh"
API="${DOORSTEP_API_URL:-http://127.0.0.1:$DOORSTEP_API_PORT}"
if curl -fsS "$API/health" >/dev/null 2>&1; then
  curl -fsS -X POST "$API/demo/reset" -H "Authorization: Bearer $DEMO_AUTH_TOKEN"
  echo
  echo "Reset via running backend at $API"
elif [ "${USE_MONGOMOCK:-false}" = "true" ]; then
  echo "Backend not running and no MONGODB_URI set: in-memory data starts fresh on next start (auto-seeded)."
else
  "$PY" - <<'PY'
from doorstep.services.db import Database
from doorstep.services.engine import DoorstepService
print(DoorstepService(Database()).reset())
PY
  echo "Reseeded $MONGODB_URI ($MONGODB_USERS_DB + $MONGODB_ORGS_DB)"
fi
