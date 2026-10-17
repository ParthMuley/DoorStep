# Shared setup for Developer B's backend scripts. Sourced, not executed.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export SIMULATION_MODE="${SIMULATION_MODE:-true}"
export DEMO_AUTH_TOKEN="${DEMO_AUTH_TOKEN:-change-me-local-demo-token}"
export DOORSTEP_API_PORT="${DOORSTEP_API_PORT:-8000}"
export DOORSTEP_DB_PATH="${DOORSTEP_DB_PATH:-$ROOT/var/doorstep_demo.db}"
if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY="$(command -v python3)"; fi
