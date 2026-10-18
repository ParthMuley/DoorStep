#!/usr/bin/env bash
# One command to check that the backend (B) and the agents (A) still fit together.
# Offline: in-memory MongoDB, ASI:One and HERE mocked, no keys needed.
#
#   scripts/check_integration.sh           # everything (~2 min)
#   scripts/check_integration.sh --quick   # skip A's full agent suite (~20 s)
#
# Stages:
#   1. backend unit tests (tests/unit)
#   2. A's agent tests exactly as A wrote them (tests/integration)
#   3. A's linking / registration / roster tests against B's REAL routes (A's stand-ins off)
#   4. smoke test: Scenarios A, B, C over real HTTP
#   5. real MongoDB tests (only if DOORSTEP_TEST_MONGODB_URI is set)
# Needs Python 3.11/3.12 with the project installed: pip install -e ".[dev]"
# Override the interpreter with CHECK_PY=/path/to/python.
set -uo pipefail
source "$(dirname "$0")/_env.sh"
cd "$ROOT"

QUICK=false
[ "${1:-}" = "--quick" ] && QUICK=true

# Tests must never call real services, whatever .env says.
export USE_MONGOMOCK=true USE_LLM_INTENT=false USE_LLM_EXTRACTION=false

pick_python() {
  for cand in "${CHECK_PY:-}" "$ROOT/.venv/bin/python" "$(command -v python3.12 || true)" "$(command -v python3.11 || true)"; do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    if "$cand" -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 13); import uagents, fastapi, mongomock, pytest' 2>/dev/null; then
      echo "$cand"; return 0
    fi
  done
  return 1
}

if ! TPY="$(pick_python)"; then
  echo "No Python 3.11/3.12 with the project's dependencies found."
  echo "Fix: python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'   (or set CHECK_PY=/path/to/python)"
  exit 2
fi
echo "Using $TPY ($("$TPY" -c 'import sys; print(sys.version.split()[0])'))"

RESULTS=()
FAILED=0
run() {  # run <name> <command...>
  local name="$1"; shift
  echo; echo "=== $name"
  local start=$SECONDS out
  out="$("$@" 2>&1)"; local code=$?
  echo "$out" | tail -n 4
  local summary
  summary="$(echo "$out" | grep -Eo '([0-9]+ (failed|passed|errors?|skipped)[^=]*)|ALL SCENARIOS PASSED.*' | tail -n 1)"
  if [ $code -eq 0 ]; then
    RESULTS+=("PASS  $name  ${summary:-ok}  ($((SECONDS - start))s)")
  else
    FAILED=1
    RESULTS+=("FAIL  $name  ${summary:-exit $code}  ($((SECONDS - start))s)")
    echo "$out" | grep -E '^(FAILED|ERROR)' | head -n 20
  fi
}

PYTEST=("$TPY" -m pytest -q -p no:cacheprovider -W ignore)

run "1. backend unit tests" "${PYTEST[@]}" tests/unit

if $QUICK; then
  RESULTS+=("SKIP  2. A's agent tests  (--quick)")
else
  run "2. A's agent tests (as written)" "${PYTEST[@]}" tests/integration
fi

STANDIN_TESTS=()
for f in tests/integration/test_rev4_linking.py tests/integration/test_rev5_registration.py tests/integration/test_roster_import.py; do
  [ -f "$f" ] && STANDIN_TESTS+=("$f")
done
if [ ${#STANDIN_TESTS[@]} -gt 0 ]; then
  run "3. A's linking tests on B's real routes" \
    env PYTHONPATH="$PYTHONPATH:$ROOT:$ROOT/scripts/checks" "${PYTEST[@]}" -p no_standins "${STANDIN_TESTS[@]}"
else
  RESULTS+=("SKIP  3. A's linking tests  (files not found)")
fi

run "4. smoke test (Scenarios A, B, C over HTTP)" env PY="$TPY" bash scripts/smoke_test.sh

if [ -n "${DOORSTEP_TEST_MONGODB_URI:-}" ]; then
  run "5. real MongoDB tests" "${PYTEST[@]}" tests/unit/test_real_mongo.py
else
  RESULTS+=("SKIP  5. real MongoDB  (set DOORSTEP_TEST_MONGODB_URI, e.g. after scripts/start_mongo.sh)")
fi

echo; echo "=================== SUMMARY (DOORSTEP DEMO, simulation) ==================="
printf '%s\n' "${RESULTS[@]}"
if [ $FAILED -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit $FAILED
