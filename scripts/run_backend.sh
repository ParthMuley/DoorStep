#!/usr/bin/env bash
# Start the Doorstep backend (SIMULATION). Usage: scripts/run_backend.sh [port]
set -euo pipefail
source "$(dirname "$0")/_env.sh"
PORT="${1:-$DOORSTEP_API_PORT}"
if [ "${USE_MONGOMOCK:-false}" = "true" ]; then
  echo "Storage: in-memory mongomock (set MONGODB_URI, e.g. via scripts/start_mongo.sh, to persist data)"
else
  echo "Storage: $MONGODB_URI ($MONGODB_USERS_DB + $MONGODB_PARTNERS_DB)"
fi
echo "Doorstep backend (SIMULATION) on http://127.0.0.1:$PORT"
exec "$PY" -m uvicorn doorstep.api.app:app --host 127.0.0.1 --port "$PORT"
