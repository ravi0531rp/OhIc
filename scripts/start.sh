#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PID=""

cleanup() {
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

(cd "$PROJECT_DIR/backend" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

if [[ ! -d "$PROJECT_DIR/dist" ]]; then
  (cd "$PROJECT_DIR" && npm run build)
fi

echo "OhIc is running at http://localhost:3000"
(cd "$PROJECT_DIR" && npm run start)
