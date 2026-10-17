#!/usr/bin/env bash
# Deterministically reset demo state to the synthetic seed.
# If the backend is running (DOORSTEP_API_URL), reset via the API; otherwise reseed the DB file.
set -euo pipefail
source "$(dirname "$0")/_env.sh"
API="${DOORSTEP_API_URL:-http://127.0.0.1:8000}"
if curl -fsS "$API/health" >/dev/null 2>&1; then
  curl -fsS -X POST "$API/demo/reset" -H "X-Demo-Token: $DOORSTEP_DEMO_TOKEN"
  echo
  echo "Reset via running backend at $API"
else
  "$PY" - <<'PY'
from doorstep.services.db import Database
from doorstep.services.engine import DoorstepService
print(DoorstepService(Database()).reset())
PY
  echo "Reseeded $DOORSTEP_DB_PATH (backend not running)"
fi
