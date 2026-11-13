#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/run-two-devices.sh" \
  --case CALL-005-ANDROID_SIGNALS \
  --case CALL-006-ANDROID_SIGNALS \
  --case CALL-007-ANDROID_SIGNALS \
  --case CHAT-006-CAMERA_VIDEO \
  --case VIDEO-FILE-OVER-100MB "$@"
