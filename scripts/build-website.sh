#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$PROJECT_DIR/_site"

if [[ "$OUTPUT_DIR" != "$PROJECT_DIR/_site" ]]; then
  echo "Unexpected website output path." >&2
  exit 1
fi

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/assets"
cp "$PROJECT_DIR/website/"*.html "$OUTPUT_DIR/"
cp "$PROJECT_DIR/website/robots.txt" "$OUTPUT_DIR/robots.txt"
cp "$PROJECT_DIR/website/sitemap.xml" "$OUTPUT_DIR/sitemap.xml"
cp -R "$PROJECT_DIR/website/assets/." "$OUTPUT_DIR/assets/"
cp "$PROJECT_DIR/public/UI1.png" "$OUTPUT_DIR/assets/ui1.png"
cp "$PROJECT_DIR/public/UI2.png" "$OUTPUT_DIR/assets/ui2.png"
cp "$PROJECT_DIR/public/sequence/pro-ai-workflow.gif" "$OUTPUT_DIR/assets/pro-ai-workflow.gif"
cp "$PROJECT_DIR/public/og.png" "$OUTPUT_DIR/og.png"
touch "$OUTPUT_DIR/.nojekyll"

echo "$OUTPUT_DIR"
