#!/usr/bin/env bash
# Start a throwaway backend on a temp DB, run Scenario A + B over real HTTP, stop it.
# No real SMS, no external services, no credentials needed.
set -euo pipefail
source "$(dirname "$0")/_env.sh"
TMP="$(mktemp -d)"
export USE_MONGOMOCK=true  # offline: in-memory MongoDB (mongomock)
PORT="${SMOKE_PORT:-$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')}"
API="http://127.0.0.1:$PORT"

"$PY" -m uvicorn doorstep.api.app:app --host 127.0.0.1 --port "$PORT" --log-level warning &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

for _ in $(seq 1 50); do
  curl -fsS "$API/health" >/dev/null 2>&1 && break
  sleep 0.2
done
curl -fsS "$API/health" >/dev/null || { echo "backend failed to start"; exit 1; }

"$PY" -m doorstep.demo.scenarios --base-url "$API" --token "$DEMO_AUTH_TOKEN"
