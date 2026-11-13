#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEST_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd -- "$TEST_ROOT"
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' "Chạy scripts/setup.sh trước." >&2
  exit 1
fi
exec .venv/bin/python -u -m tammi_runner.cli preflight "$@"
