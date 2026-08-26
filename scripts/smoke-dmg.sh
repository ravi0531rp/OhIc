#!/bin/bash
set -euo pipefail

DMG_PATH="${1:?Usage: scripts/smoke-dmg.sh path/to/OhIc.dmg}"
MOUNT_DIR="$(mktemp -d "${TMPDIR%/}/ohic-mount.XXXXXX")"
SMOKE_DIR="$(mktemp -d "${TMPDIR%/}/ohic-smoke.XXXXXX")"
FRONTEND_PID=""
APPLICATION_PID=""

cleanup() {
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$APPLICATION_PID" ]]; then
    kill "$APPLICATION_PID" 2>/dev/null || true
    wait "$APPLICATION_PID" 2>/dev/null || true
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
MOUNTED_APP_DIR="$MOUNT_DIR/OhIc.app"
APP_DIR="$SMOKE_DIR/OhIc.app"
ditto "$MOUNTED_APP_DIR" "$APP_DIR"
RESOURCE_DIR="$APP_DIR/Contents/Resources"

codesign --verify --deep --strict "$APP_DIR"
OHIC_DATA_DIR="$SMOKE_DIR/data" \
  PYTHONHOME="$RESOURCE_DIR/python" \
  PYTHONPATH="$RESOURCE_DIR/backend:$RESOURCE_DIR/python-packages" \
  PYTHONPYCACHEPREFIX="$SMOKE_DIR/pycache" \
  "$RESOURCE_DIR/python/bin/python3" -c \
  "import uvicorn; from app.schemas.video import CameraSession; print('backend-runtime-ok')"
codesign --verify --deep --strict "$APP_DIR"
if find "$APP_DIR" -type d -name '__pycache__' -print -quit | grep -q .; then
  echo "Python wrote bytecode inside the signed application." >&2
  exit 1
fi
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
    break
  fi
  sleep 0.5
done

if ! grep -Fq "Private local video studio" "$SMOKE_DIR/home.html" 2>/dev/null; then
  cat "$SMOKE_DIR/frontend.log" >&2
  exit 1
fi
kill "$FRONTEND_PID" 2>/dev/null || true
wait "$FRONTEND_PID" 2>/dev/null || true
FRONTEND_PID=""

mkdir -p "$SMOKE_DIR/home"
file "$APP_DIR/Contents/MacOS/OhIc" | grep -Fq "Mach-O"
HOME="$SMOKE_DIR/home" OHIC_SMOKE_TEST=1 "$APP_DIR/Contents/MacOS/OhIc" \
  >"$SMOKE_DIR/native-host.log" 2>&1 &
APPLICATION_PID=$!
APPLICATION_OK=0
for _attempt in {1..120}; do
  if curl --silent --fail http://127.0.0.1:8000/api/health >/dev/null \
    && curl --silent --fail http://127.0.0.1:3000/ >/dev/null \
    && grep -Fq "native-host-ready" "$SMOKE_DIR/native-host.log"; then
    APPLICATION_OK=1
    break
  fi
  if ! kill -0 "$APPLICATION_PID" 2>/dev/null; then
    break
  fi
  sleep 0.5
done
if [[ "$APPLICATION_OK" -ne 1 ]]; then
  cat "$SMOKE_DIR/native-host.log" 2>/dev/null || true
  cat "$SMOKE_DIR/home/Library/Logs/OhIc/backend.log" 2>/dev/null || true
  cat "$SMOKE_DIR/home/Library/Logs/OhIc/frontend.log" 2>/dev/null || true
  exit 1
fi
echo "native-application-runtime-ok"
kill "$APPLICATION_PID" 2>/dev/null || true
wait "$APPLICATION_PID" 2>/dev/null || true
APPLICATION_PID=""
for _attempt in {1..20}; do
  if ! curl --silent --fail --max-time 0.25 http://127.0.0.1:8000/api/health >/dev/null 2>&1 \
    && ! curl --silent --fail --max-time 0.25 http://127.0.0.1:3000/ >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if curl --silent --fail --max-time 0.25 http://127.0.0.1:8000/api/health >/dev/null 2>&1 \
  || curl --silent --fail --max-time 0.25 http://127.0.0.1:3000/ >/dev/null 2>&1; then
  echo "Native application left local services running after termination." >&2
  exit 1
fi
codesign --verify --deep --strict "$APP_DIR"
