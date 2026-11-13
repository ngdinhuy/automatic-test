#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEST_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
test_run_exit=0
"$SCRIPT_DIR/run.sh" "$@" --suite pair || test_run_exit=$?
if [[ -x "$TEST_ROOT/.venv/bin/python" ]]; then
  "$TEST_ROOT/.venv/bin/python" "$SCRIPT_DIR/summarize-results.py" || { if [[ "$test_run_exit" -eq 0 ]]; then test_run_exit=2; fi; }
  "$TEST_ROOT/.venv/bin/python" "$SCRIPT_DIR/summarize-pair.py" || { if [[ "$test_run_exit" -eq 0 ]]; then test_run_exit=2; fi; }
  "$TEST_ROOT/.venv/bin/python" "$SCRIPT_DIR/summarize-completion.py" || { if [[ "$test_run_exit" -eq 0 ]]; then test_run_exit=2; fi; }
fi
exit "$test_run_exit"
