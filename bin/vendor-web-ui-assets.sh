#!/usr/bin/env bash
# Download pinned third-party JS for jarvis-web (offline + reproducible builds).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/jarvis-web/client/vendor"
mkdir -p "$VENDOR"

MARKED_VER="15.0.6"
SOCKET_VER="4.7.2"

echo "Fetching marked@${MARKED_VER}..."
curl -fsSL -o "$VENDOR/marked.min.js" \
  "https://cdn.jsdelivr.net/npm/marked@${MARKED_VER}/marked.min.js"

echo "Fetching socket.io-client ${SOCKET_VER}..."
curl -fsSL -o "$VENDOR/socket.io.min.js" \
  "https://cdn.socket.io/${SOCKET_VER}/socket.io.min.js"

wc -c "$VENDOR"/*.js

# Jarvis Canvas (markdown + sanitize + highlight)
CANVAS_VENDOR="$ROOT/jarvis-canvas/client/static/vendor"
mkdir -p "$CANVAS_VENDOR"
PURIFY_VER="3.0.6"
HLJS_VER="11.9.0"

echo "Fetching Canvas marked@${MARKED_VER}..."
curl -fsSL -o "$CANVAS_VENDOR/marked.min.js" \
  "https://cdn.jsdelivr.net/npm/marked@${MARKED_VER}/marked.min.js"
echo "Fetching dompurify@${PURIFY_VER}..."
curl -fsSL -o "$CANVAS_VENDOR/purify.min.js" \
  "https://cdn.jsdelivr.net/npm/dompurify@${PURIFY_VER}/dist/purify.min.js"
echo "Fetching highlight.js ${HLJS_VER}..."
curl -fsSL -o "$CANVAS_VENDOR/highlight.min.js" \
  "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/${HLJS_VER}/highlight.min.js"
curl -fsSL -o "$CANVAS_VENDOR/highlight-github-dark.min.css" \
  "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/${HLJS_VER}/styles/github-dark.min.css"

wc -c "$CANVAS_VENDOR"/* 2>/dev/null || true
echo "Done. Update jarvis-web/client/vendor/README.md if versions change."
