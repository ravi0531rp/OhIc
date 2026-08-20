#!/usr/bin/env bash
set -Eeuo pipefail

IFS=$'\n\t'

OHIC_REPOSITORY="${OHIC_REPOSITORY:-ravi0531rp/OhIc}"
OHIC_REF="${OHIC_REF:-main}"
FRONTEND_URL="http://localhost:3000"
BACKEND_URL="http://127.0.0.1:8000"
INSTALL_ONLY=0
NO_OPEN=0
UPDATE=0
DOCTOR=0
INSTALLED_MODE="${OHIC_INSTALLED:-0}"
BACKEND_PID=""
FRONTEND_PID=""
TEMP_DIR=""

say() {
  printf '\n\033[1;32mOhIc\033[0m  %s\n' "$*"
}

note() {
  printf '      %s\n' "$*"
}

fail() {
  printf '\nOhIc could not continue: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Install, repair, update, and run OhIc with one script.

Usage: bash install.sh [options]

  --install-only  Install and verify OhIc without starting it
  --no-open       Start OhIc without opening a browser
  --update        Download the latest configured release before starting
  --doctor        Check this computer without installing anything
  --help          Show this help

Environment overrides:
  OHIC_HOME        Installation and application-data directory
  OHIC_REPOSITORY  GitHub owner/repository (default: ravi0531rp/OhIc)
  OHIC_REF         Git branch or tag to install (default: main)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-only) INSTALL_ONLY=1 ;;
    --no-open) NO_OPEN=1 ;;
    --update) UPDATE=1 ;;
    --doctor) DOCTOR=1 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "Unknown option: $1. Run with --help for usage." ;;
  esac
  shift
done

case "$(uname -s)" in
  Darwin)
    PLATFORM="macos"
    DEFAULT_HOME="$HOME/Library/Application Support/OhIc"
    ;;
  Linux)
    PLATFORM="linux"
    DEFAULT_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/ohic"
    ;;
  *) fail "This installer currently supports macOS and Linux." ;;
esac

OHIC_HOME="${OHIC_HOME:-$DEFAULT_HOME}"
TOOLS_DIR="$OHIC_HOME/tools"
DATA_DIR="$OHIC_HOME/data"
RUN_DIR="$OHIC_HOME/run"
RELEASES_DIR="$OHIC_HOME/releases"
CURRENT_LINK="$OHIC_HOME/current"
USER_BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""

if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
fi

LOCAL_SOURCE=""
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/package.json" && -f "$SCRIPT_DIR/backend/pyproject.toml" ]]; then
  LOCAL_SOURCE="$SCRIPT_DIR"
fi

cleanup() {
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    find "$TEMP_DIR" -depth -delete 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

prepend_tool_paths() {
  export PATH="$TOOLS_DIR/node/current/bin:$TOOLS_DIR/uv/bin:$HOME/.local/bin:$PATH"
}

command_version() {
  if command -v "$1" >/dev/null 2>&1; then
    "$1" "${2:---version}" 2>/dev/null | head -n 1 || true
  else
    printf 'not found'
  fi
}

node_is_supported() {
  command -v node >/dev/null 2>&1 || return 1
  local major
  major="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || printf '0')"
  [[ "$major" =~ ^[0-9]+$ ]] && (( major >= 22 ))
}

run_doctor() {
  prepend_tool_paths
  say "Computer check"
  note "Platform: $PLATFORM ($(uname -m))"
  note "curl: $(command_version curl)"
  note "tar: $(command_version tar --version)"
  note "uv: $(command_version uv)"
  note "Python: $(command_version python3)"
  note "Node: $(command_version node)"
  note "npm: $(command_version npm)"
  note "FFmpeg: $(command_version ffmpeg -version)"
  note "FFprobe: $(command_version ffprobe -version)"
  if [[ -d "$CURRENT_LINK" || -L "$CURRENT_LINK" ]]; then
    note "Installed source: $CURRENT_LINK"
  elif [[ -n "$LOCAL_SOURCE" ]]; then
    note "Local source: $LOCAL_SOURCE"
  else
    note "OhIc is not installed yet. Run this script without --doctor."
  fi
}

if (( DOCTOR )); then
  run_doctor
  exit 0
fi

command -v curl >/dev/null 2>&1 || fail "curl is required to download the installer components."
command -v tar >/dev/null 2>&1 || fail "tar is required to unpack the application."

mkdir -p "$TOOLS_DIR" "$DATA_DIR" "$RUN_DIR" "$RELEASES_DIR" "$USER_BIN_DIR"
prepend_tool_paths

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    note "uv $(uv --version | awk '{print $2}')"
    return
  fi
  say "Installing the isolated Python toolchain"
  mkdir -p "$TOOLS_DIR/uv/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$TOOLS_DIR/uv/bin" sh
  prepend_tool_paths
  command -v uv >/dev/null 2>&1 || fail "uv installation did not produce an executable."
}

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    fail "A SHA-256 utility is required to verify downloads."
  fi
}

install_node() {
  if node_is_supported && command -v npm >/dev/null 2>&1; then
    note "Node $(node --version)"
    return
  fi

  say "Installing a private Node.js runtime"
  local node_platform node_arch archive_type version archive base_url expected actual destination
  case "$PLATFORM" in
    macos) node_platform="darwin"; archive_type="tar.gz" ;;
    linux) node_platform="linux"; archive_type="tar.xz" ;;
  esac
  case "$(uname -m)" in
    arm64|aarch64) node_arch="arm64" ;;
    x86_64|amd64) node_arch="x64" ;;
    *) fail "Node.js does not publish a supported binary for $(uname -m)." ;;
  esac

  version="$(curl -fsSL https://nodejs.org/dist/index.json \
    | tr '{' '\n' \
    | sed -n 's/.*"version":"\(v22\.[0-9.]*\)".*/\1/p' \
    | head -n 1)"
  [[ -n "$version" ]] || fail "Could not resolve a supported Node.js 22 release."
  archive="node-$version-$node_platform-$node_arch.$archive_type"
  base_url="https://nodejs.org/dist/$version"
  TEMP_DIR="${TEMP_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/ohic-install.XXXXXX")}"
  curl -fL --retry 3 --output "$TEMP_DIR/$archive" "$base_url/$archive"
  expected="$(curl -fsSL "$base_url/SHASUMS256.txt" | awk -v file="$archive" '$2 == file {print $1}')"
  actual="$(sha256_file "$TEMP_DIR/$archive")"
  [[ -n "$expected" && "$expected" == "$actual" ]] || fail "Node.js checksum verification failed."

  destination="$TOOLS_DIR/node/$version"
  if [[ ! -d "$destination" ]]; then
    mkdir -p "$destination"
    tar -xf "$TEMP_DIR/$archive" --strip-components=1 -C "$destination"
  fi
  mkdir -p "$TOOLS_DIR/node"
  ln -sfn "$destination" "$TOOLS_DIR/node/current"
  prepend_tool_paths
  node_is_supported || fail "The private Node.js runtime could not be started."
  command -v npm >/dev/null 2>&1 || fail "npm was missing from the Node.js installation."
}

as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    fail "Administrator access is required to install FFmpeg."
  fi
}

install_ffmpeg() {
  if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    note "FFmpeg and FFprobe are available"
    return
  fi

  say "Installing FFmpeg and FFprobe"
  if [[ "$PLATFORM" == "macos" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
      note "Homebrew is needed for the signed macOS FFmpeg distribution."
      NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
      elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
      fi
    fi
    command -v brew >/dev/null 2>&1 || fail "Homebrew installation did not complete."
    brew install ffmpeg
  elif command -v apt-get >/dev/null 2>&1; then
    as_root apt-get update
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg
  elif command -v dnf >/dev/null 2>&1; then
    as_root dnf install -y ffmpeg
  elif command -v yum >/dev/null 2>&1; then
    as_root yum install -y ffmpeg
  elif command -v pacman >/dev/null 2>&1; then
    as_root pacman -Sy --needed --noconfirm ffmpeg
  elif command -v zypper >/dev/null 2>&1; then
    as_root zypper --non-interactive install ffmpeg
  else
    fail "No supported system package manager was found for FFmpeg."
  fi

  command -v ffmpeg >/dev/null 2>&1 || fail "FFmpeg installation did not complete."
  command -v ffprobe >/dev/null 2>&1 || fail "FFprobe installation did not complete."
}

download_source() {
  say "Downloading OhIc"
  TEMP_DIR="${TEMP_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/ohic-install.XXXXXX")}"
  local archive release_id release_dir
  archive="$TEMP_DIR/ohic.tar.gz"
  release_id="$(date +%Y%m%d%H%M%S)-$$"
  release_dir="$RELEASES_DIR/$release_id"
  mkdir -p "$release_dir"
  curl -fL --retry 3 \
    --output "$archive" \
    "https://github.com/$OHIC_REPOSITORY/archive/$OHIC_REF.tar.gz"
  tar -xzf "$archive" --strip-components=1 -C "$release_dir"
  [[ -f "$release_dir/package.json" && -f "$release_dir/backend/pyproject.toml" ]] \
    || fail "The downloaded archive is not a complete OhIc release."
  ln -sfn "$release_dir" "$CURRENT_LINK"
  SOURCE_DIR="$release_dir"
}

if [[ -n "$LOCAL_SOURCE" && "$INSTALLED_MODE" != "1" && "$SCRIPT_PATH" != "$CURRENT_LINK/"* ]]; then
  SOURCE_DIR="$LOCAL_SOURCE"
  if (( UPDATE )); then
    note "--update is ignored when running from a local source checkout."
  fi
elif (( UPDATE )) || [[ ! -f "$CURRENT_LINK/package.json" ]]; then
  download_source
else
  SOURCE_DIR="$CURRENT_LINK"
fi

install_uv
install_node
install_ffmpeg

mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/downloads" "$DATA_DIR/jobs" \
  "$DATA_DIR/outputs" "$DATA_DIR/models" "$DATA_DIR/temp"
export OHIC_DATA_DIR="$DATA_DIR"
export OHIC_MODEL_DIR="$DATA_DIR/models"
export OHIC_FRONTEND_ORIGIN="$FRONTEND_URL"

SOURCE_REAL="$(cd "$SOURCE_DIR" && pwd -P)"
SETUP_STAMP=""
if [[ "$SOURCE_REAL" == "$RELEASES_DIR/"* ]]; then
  SETUP_STAMP="$RUN_DIR/setup-$(basename "$SOURCE_REAL")"
fi

if [[ -z "$SETUP_STAMP" || ! -f "$SETUP_STAMP" ]]; then
  say "Preparing OhIc"
  uv python install 3.12
  (cd "$SOURCE_DIR/backend" && uv sync --frozen --no-dev --python 3.12)
  (cd "$SOURCE_DIR" && npm ci --no-audit --no-fund)
  (cd "$SOURCE_DIR" && NEXT_PUBLIC_API_URL="$BACKEND_URL" npm run build)

  say "Verifying the installation"
  (cd "$SOURCE_DIR/backend" && uv run --no-dev python -c \
    'import app.main; print("      Backend imports successfully")')
  note "Frontend production build is ready"
  if [[ -n "$SETUP_STAMP" ]]; then
    : > "$SETUP_STAMP"
  fi
else
  note "The installed release is already prepared"
fi

if [[ "$SOURCE_DIR" == "$CURRENT_LINK" || "$SOURCE_DIR" == "$RELEASES_DIR"/* ]]; then
  printf '#!/usr/bin/env bash\nOHIC_INSTALLED=1 exec %q "$@"\n' \
    "$CURRENT_LINK/install.sh" > "$USER_BIN_DIR/ohic"
else
  printf '#!/usr/bin/env bash\nexec %q "$@"\n' \
    "$SOURCE_DIR/install.sh" > "$USER_BIN_DIR/ohic"
fi
chmod +x "$USER_BIN_DIR/ohic"

if (( INSTALL_ONLY )); then
  say "Installation complete"
  note "Start OhIc with: $USER_BIN_DIR/ohic"
  exit 0
fi

if curl -fsS "$BACKEND_URL/api/health" >/dev/null 2>&1 \
  && curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
  say "OhIc is already running at $FRONTEND_URL"
else
  if curl -sS --max-time 1 "$BACKEND_URL" >/dev/null 2>&1; then
    fail "Port 8000 is already being used by another application."
  fi
  if curl -sS --max-time 1 "$FRONTEND_URL" >/dev/null 2>&1; then
    fail "Port 3000 is already being used by another application."
  fi

  say "Starting OhIc"
  (cd "$SOURCE_DIR/backend" && uv run --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000) &
  BACKEND_PID=$!
  (cd "$SOURCE_DIR" && npm run start -- -H 127.0.0.1 -p 3000) &
  FRONTEND_PID=$!

  ready=0
  attempt=0
  while (( attempt < 60 )); do
    if curl -fsS "$BACKEND_URL/api/health" >/dev/null 2>&1 \
      && curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
      ready=1
      break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      break
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  (( ready )) || fail "The local services did not become ready. Review the messages above."
  say "OhIc is ready at $FRONTEND_URL"
fi

if (( ! NO_OPEN )); then
  if [[ "$PLATFORM" == "macos" ]]; then
    open "$FRONTEND_URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$FRONTEND_URL" >/dev/null 2>&1 || true
  elif command -v gio >/dev/null 2>&1; then
    gio open "$FRONTEND_URL" >/dev/null 2>&1 || true
  fi
fi

if [[ -n "$FRONTEND_PID" ]]; then
  note "Keep this terminal open. Press Control-C to stop OhIc."
  wait "$FRONTEND_PID"
fi
