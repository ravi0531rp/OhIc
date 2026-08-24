#!/bin/bash
set -euo pipefail

DMG_PATH="${1:?Usage: scripts/smoke-dmg.sh path/to/OhIc.dmg}"
MOUNT_DIR="$(mktemp -d "${TMPDIR%/}/ohic-mount.XXXXXX")"
SMOKE_DIR="$(mktemp -d "${TMPDIR%/}/ohic-smoke.XXXXXX")"
FRONTEND_PID=""

cleanup() {
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  hdiutil detach "$MOUNT_DIR" >/dev/null 2>&1 || true
  if ! mount | grep -Fq " on $MOUNT_DIR ("; then
    rm -rf "$MOUNT_DIR"
  fi
  rm -rf "$SMOKE_DIR"
}
trap cleanup EXIT

hdiutil verify -quiet "$DMG_PATH"
hdiutil attach -nobrowse -mountpoint "$MOUNT_DIR" "$DMG_PATH" >/dev/null
APP_DIR="$MOUNT_DIR/OhIc.app"
RESOURCE_DIR="$APP_DIR/Contents/Resources"

codesign --verify --deep --strict "$APP_DIR"
OHIC_DATA_DIR="$SMOKE_DIR/data" \
  PYTHONHOME="$RESOURCE_DIR/python" \
  PYTHONPATH="$RESOURCE_DIR/backend:$RESOURCE_DIR/python-packages" \
  "$RESOURCE_DIR/python/bin/python3" -c \
  "import uvicorn; from app.schemas.video import CameraSession; print('backend-runtime-ok')"
"$RESOURCE_DIR/bin/ffmpeg" -version | head -n 1
"$RESOURCE_DIR/bin/uv" --version

DYLD_LIBRARY_PATH="$RESOURCE_DIR/lib" HOSTNAME=127.0.0.1 PORT=3199 \
  "$RESOURCE_DIR/bin/node" "$RESOURCE_DIR/frontend/server.js" \
  >"$SMOKE_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

for _attempt in {1..20}; do
  if curl --silent --fail http://127.0.0.1:3199/ >"$SMOKE_DIR/home.html"; then
    grep -Fq "Private local video studio" "$SMOKE_DIR/home.html"
    echo "frontend-runtime-ok"
    exit 0
  fi
  sleep 0.5
done

cat "$SMOKE_DIR/frontend.log" >&2
exit 1
