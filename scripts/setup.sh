#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "FFmpeg and FFprobe are required. Install FFmpeg for your operating system, then retry."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 22 or newer is required."
  exit 1
fi

echo "Setting up the enhancement engine…"
(cd "$PROJECT_DIR/backend" && uv sync --group dev)

echo "Setting up the workspace…"
(cd "$PROJECT_DIR" && npm install)

mkdir -p "$PROJECT_DIR/data/uploads" "$PROJECT_DIR/data/downloads" \
  "$PROJECT_DIR/data/jobs" "$PROJECT_DIR/data/outputs" \
  "$PROJECT_DIR/data/models" "$PROJECT_DIR/data/temp"

echo "OhIc is ready. Run ./scripts/dev.sh"
