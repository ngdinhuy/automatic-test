#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEST_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd -- "$TEST_ROOT"
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "Cần Python 3.10+; đặt PYTHON_BIN trỏ đến Python phù hợp."'
if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.lock
export npm_config_cache="$TEST_ROOT/.runtime/npm-cache"
if [[ -f package-lock.json ]]; then
  npm ci --no-audit --no-fund
else
  npm install --no-audit --no-fund
fi
export APPIUM_HOME="$TEST_ROOT/.runtime/appium"
if [[ ! -f "$APPIUM_HOME/node_modules/appium-uiautomator2-driver/package.json" ]]; then
  node_modules/.bin/appium driver install uiautomator2@8.6.0
fi
.venv/bin/python scripts/configure-defaults.py
printf '%s\n' "Setup hoàn tất. Mở Launch.command hoặc chạy scripts/desktop.sh."
