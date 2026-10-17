# Shared setup for Developer B's backend scripts. Sourced, not executed.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export SIMULATION_MODE="${SIMULATION_MODE:-true}"
export DOORSTEP_DEMO_TOKEN="${DOORSTEP_DEMO_TOKEN:-doorstep-local-demo-token}"
export DOORSTEP_DB_PATH="${DOORSTEP_DB_PATH:-$ROOT/var/doorstep_demo.db}"
if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY="$(command -v python3)"; fi
