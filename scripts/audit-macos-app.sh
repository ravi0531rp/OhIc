#!/bin/bash
set -euo pipefail

APP_DIR="${1:?Usage: scripts/audit-macos-app.sh path/to/OhIc.app}"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS bundle auditing requires macOS." >&2
  exit 1
fi
if [[ ! -d "$APP_DIR/Contents/Resources" ]]; then
  echo "Not an OhIc application bundle: $APP_DIR" >&2
  exit 1
fi

RESOURCE_DIR="$APP_DIR/Contents/Resources"
REQUIRED=(
  "$APP_DIR/Contents/MacOS/OhIc"
  "$RESOURCE_DIR/backend_entry.py"
  "$RESOURCE_DIR/frontend/server.js"
  "$RESOURCE_DIR/python/bin/python3"
  "$RESOURCE_DIR/bin/node"
  "$RESOURCE_DIR/bin/ffmpeg"
  "$RESOURCE_DIR/bin/ffprobe"
  "$RESOURCE_DIR/bin/uv"
)
for path in "${REQUIRED[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "Required application resource is missing: $path" >&2
    exit 1
  fi
done

BROKEN_LINKS="$(find -L "$APP_DIR" -type l -print)"
if [[ -n "$BROKEN_LINKS" ]]; then
  echo "The application contains broken symbolic links:" >&2
  printf '%s\n' "$BROKEN_LINKS" >&2
  exit 1
fi

FAILURES=0
while IFS= read -r -d '' binary; do
  if ! file -b "$binary" | grep -q 'Mach-O'; then
    continue
  fi
  while IFS= read -r dependency; do
    case "$dependency" in
      @*|/usr/lib/*|/System/Library/*) ;;
      *)
        echo "Non-relocatable dependency: $binary -> $dependency" >&2
        FAILURES=1
        ;;
    esac
  done < <(
    otool -l "$binary" 2>/dev/null | awk '
      $1 == "cmd" {
        load = ($2 ~ /^LC_(LOAD|LOAD_WEAK|REEXPORT|LOAD_UPWARD)_DYLIB$/)
      }
      load && $1 == "name" {
        print $2
        load = 0
      }
    '
  )
done < <(
  find "$APP_DIR" -type f \
    \( -perm -111 -o -name '*.dylib' -o -name '*.so' \) -print0
)
if [[ "$FAILURES" -ne 0 ]]; then
  echo "OhIc still depends on libraries from the build Mac." >&2
  exit 1
fi

for executable in \
  "$APP_DIR/Contents/MacOS/OhIc" \
  "$RESOURCE_DIR/bin/node" \
  "$RESOURCE_DIR/bin/ffmpeg" \
  "$RESOURCE_DIR/bin/ffprobe"; do
  if ! lipo -archs "$executable" | tr ' ' '\n' | grep -qx arm64; then
    echo "Apple silicon executable is missing arm64 support: $executable" >&2
    exit 1
  fi
done

echo "standalone-bundle-audit-ok"
