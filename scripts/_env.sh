# Shared setup for Developer B's backend scripts. Sourced, not executed.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export SIMULATION_MODE="${SIMULATION_MODE:-true}"
export DEMO_AUTH_TOKEN="${DEMO_AUTH_TOKEN:-change-me-local-demo-token}"
export DOORSTEP_API_PORT="${DOORSTEP_API_PORT:-8000}"
export MONGODB_USERS_DB="${MONGODB_USERS_DB:-doorstep_users}"
export MONGODB_PARTNERS_DB="${MONGODB_PARTNERS_DB:-${MONGODB_ORGS_DB:-doorstep_partners}}"
# No MONGODB_URI configured -> in-memory mongomock (data is lost when the backend stops).
if [ -z "${MONGODB_URI:-}" ]; then export USE_MONGOMOCK="${USE_MONGOMOCK:-true}"; fi
if [ -n "${PY:-}" ]; then :  # caller chose the interpreter
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY="$(command -v python3)"; fi
