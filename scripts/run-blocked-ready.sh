#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/run-two-devices.sh" --skip-passed --skip-failed \
  --case CHAT-023-OTHER_CONVERSATION \
  --case CALL-040-CAMERA_ON \
  --case CALL-040-CAMERA_OFF \
  --case CALL-041-CAMERA_ON \
  --case CALL-041-CAMERA_OFF "$@"
