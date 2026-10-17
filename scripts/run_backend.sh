#!/usr/bin/env bash
# Start the Doorstep backend (SIMULATION). Usage: scripts/run_backend.sh [port]
set -euo pipefail
source "$(dirname "$0")/_env.sh"
PORT="${1:-${DOORSTEP_PORT:-8000}}"
echo "Doorstep backend (SIMULATION) on http://127.0.0.1:$PORT  db=$DOORSTEP_DB_PATH"
exec "$PY" -m uvicorn doorstep.api.app:app --host 127.0.0.1 --port "$PORT"
