#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "DMG packaging requires macOS." >&2
  exit 1
fi

VERSION="${OHIC_BUILD_VERSION:-$(node -p "require('$PROJECT_DIR/package.json').version")}"
SAFE_VERSION="${VERSION//\//-}"
RELEASE_DIR="$PROJECT_DIR/release"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ohic-dmg.XXXXXX")"
APP_DIR="$WORK_DIR/image/OhIc.app"
RESOURCE_DIR="$APP_DIR/Contents/Resources"
trap 'rm -rf "$WORK_DIR"' EXIT

if [[ "${OHIC_SKIP_BUILD:-0}" != "1" ]]; then
  (cd "$PROJECT_DIR" && npm run build)
fi
if [[ ! -f "$PROJECT_DIR/dist/standalone/server.js" ]]; then
  echo "Standalone frontend output is missing." >&2
  exit 1
fi

PYTHON_BIN="$(cd "$PROJECT_DIR/backend" && uv run python -c 'import sys; print(sys.executable)')"
PYTHON_PREFIX="$($PYTHON_BIN -c 'import sys; print(sys.base_prefix)')"
SITE_PACKAGES="$($PYTHON_BIN -c 'import site; print(site.getsitepackages()[0])')"
NODE_BIN="$(command -v node)"
NODE_REAL="$($PYTHON_BIN -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$NODE_BIN")"
NODE_PREFIX="$(cd "$(dirname "$NODE_REAL")/.." && pwd)"
FFMPEG_BIN="$(command -v ffmpeg)"
FFPROBE_BIN="$(command -v ffprobe)"
UV_BIN="$(command -v uv)"
CLOUDFLARED_BIN="$(command -v cloudflared || true)"
if [[ -z "$CLOUDFLARED_BIN" ]]; then
  echo "cloudflared is required for secure phone streaming. Install it with: brew install cloudflared" >&2
  exit 1
fi

mkdir -p "$APP_DIR/Contents/MacOS" "$RESOURCE_DIR/bin" "$RESOURCE_DIR/lib" "$WORK_DIR/image" "$RELEASE_DIR"
cp "$PROJECT_DIR/packaging/OhIc" "$APP_DIR/Contents/MacOS/OhIc"
chmod +x "$APP_DIR/Contents/MacOS/OhIc"
cp "$PROJECT_DIR/packaging/Info.plist" "$APP_DIR/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP_DIR/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${GITHUB_RUN_NUMBER:-1}" "$APP_DIR/Contents/Info.plist"

cp -R "$PROJECT_DIR/dist/standalone" "$RESOURCE_DIR/frontend"
# vinext's standalone tracer currently omits these peer runtime packages and
# succeeds in a checkout only because Node walks up to the repository modules.
for FRONTEND_PACKAGE in react react-dom scheduler; do
  cp -R "$PROJECT_DIR/node_modules/$FRONTEND_PACKAGE" "$RESOURCE_DIR/frontend/node_modules/$FRONTEND_PACKAGE"
done
mkdir -p "$RESOURCE_DIR/backend"
cp -R "$PROJECT_DIR/backend/app" "$RESOURCE_DIR/backend/app"
cp "$PROJECT_DIR/packaging/backend_entry.py" "$RESOURCE_DIR/backend_entry.py"
cp -R "$PYTHON_PREFIX" "$RESOURCE_DIR/python"
cp -R "$SITE_PACKAGES" "$RESOURCE_DIR/python-packages"
cp "$NODE_BIN" "$RESOURCE_DIR/bin/node"
cp "$FFMPEG_BIN" "$RESOURCE_DIR/bin/ffmpeg"
cp "$FFPROBE_BIN" "$RESOURCE_DIR/bin/ffprobe"
cp "$UV_BIN" "$RESOURCE_DIR/bin/uv"
cp "$CLOUDFLARED_BIN" "$RESOURCE_DIR/bin/cloudflared"
chmod +x "$RESOURCE_DIR/bin/cloudflared"
if command -v dylibbundler >/dev/null 2>&1; then
  if ! dylibbundler -od -b \
    -x "$RESOURCE_DIR/bin/node" \
    -x "$RESOURCE_DIR/bin/ffmpeg" \
    -x "$RESOURCE_DIR/bin/ffprobe" \
    -s "$NODE_PREFIX/lib" \
    -d "$RESOURCE_DIR/lib" \
    -p @executable_path/../lib >"$WORK_DIR/dylibbundler.log" 2>&1; then
    cat "$WORK_DIR/dylibbundler.log" >&2
    exit 1
  fi
  # dylibbundler 1.0.5 adds the same LC_RPATH twice when resolving
  # transitive Homebrew dependencies; modern dyld rejects that binary.
  for BUNDLED_EXECUTABLE in "$RESOURCE_DIR/bin/node" "$RESOURCE_DIR/bin/ffmpeg" "$RESOURCE_DIR/bin/ffprobe"; do
    RPATH_COUNT="$(otool -l "$BUNDLED_EXECUTABLE" | awk '/cmd LC_RPATH/{getline; getline; if ($1 == "path" && $2 == "@executable_path/../lib/") count++} END {print count+0}')"
    if [[ "$RPATH_COUNT" -gt 1 ]]; then
      install_name_tool -delete_rpath '@executable_path/../lib/' "$BUNDLED_EXECUTABLE"
    fi
    # install_name_tool invalidates dylibbundler's ad-hoc signature.
    codesign --force --sign - "$BUNDLED_EXECUTABLE"
  done
  codesign --force --sign - "$RESOURCE_DIR/bin/cloudflared"
else
  echo "dylibbundler is required to make Node and FFmpeg relocatable." >&2
  exit 1
fi
ln -s /Applications "$WORK_DIR/image/Applications"

find "$APP_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
xattr -cr "$APP_DIR" 2>/dev/null || true
codesign --force --deep --sign - "$APP_DIR"
DMG_PATH="$RELEASE_DIR/OhIc-$SAFE_VERSION.dmg"
rm -f "$DMG_PATH"
hdiutil create -quiet -volname "OhIc $VERSION" -srcfolder "$WORK_DIR/image" \
  -format UDZO -imagekey zlib-level=9 "$DMG_PATH"
echo "$DMG_PATH"
