#!/bin/bash
# Jarvis Voice Assistant - Status Update TTS (Local/Kokoro)
# Lightweight TTS for local mode - reuses existing Kokoro TTS config
#
# Usage: say-status-local.sh "message" [blocking]
#   blocking: "true" (wait for playback) or "false" (background)

set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"

TEXT="${1:-}"
BLOCKING="${2:-true}"

if [ -z "$TEXT" ]; then
    echo "Usage: $0 <text to speak> [blocking]" >&2
    exit 1
fi

# Use temp file for status audio (short-lived, no need to save)
OUTFILE="/tmp/jarvis-status-local-$$.wav"

# Sanitize: collapse whitespace, strip control chars
SANITIZED=$(printf "%s" "$TEXT" \
  | tr -d '\000' \
  | tr '\r' '\n' \
  | sed 's/[[:cntrl:]]//g' \
  | sed 's/[[:space:]]\+/ /g' \
  | sed 's/^ *//;s/ *$//')

# Build JSON and call Kokoro TTS (same as say-local.sh)
TTS_JSON=$(jq -n \
  --arg voice "$TTS_VOICE" \
  --arg input "$SANITIZED" \
  --arg speed "$TTS_SPEED" \
  '{voice:$voice, input:$input, speed:$speed}')

# Generate TTS audio via Kokoro
if ! curl -sS -X POST "$TTS_URL" \
    -H "Content-Type: application/json" \
    -d "$TTS_JSON" \
    | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null; then
    echo "⚠️ Local TTS generation failed" >&2
    exit 1
fi

# Check if audio was generated
if [ ! -f "$OUTFILE" ] || [ ! -s "$OUTFILE" ]; then
    echo "⚠️ TTS output empty" >&2
    exit 1
fi

# Silence padding (ms) - helps speakers "wake up" before speech starts
SILENCE_PAD_MS="${STATUS_SILENCE_PAD_MS:-250}"

# Add silence padding at the beginning (helps Bluetooth/wireless speakers wake up)
if command -v sox &>/dev/null && [ "$SILENCE_PAD_MS" -gt 0 ]; then
    PADDED_FILE="/tmp/jarvis-status-local-padded-$$.wav"
    # Convert ms to seconds for sox (e.g., 250ms = 0.25s)
    SILENCE_SECS=$(echo "scale=3; $SILENCE_PAD_MS / 1000" | bc)
    sox -n -r "$RATE" -c 2 -b 16 "/tmp/jarvis-silence-local-$$.wav" trim 0.0 "$SILENCE_SECS" 2>/dev/null
    sox "/tmp/jarvis-silence-local-$$.wav" "$OUTFILE" "$PADDED_FILE" 2>/dev/null
    mv "$PADDED_FILE" "$OUTFILE"
    rm -f "/tmp/jarvis-silence-local-$$.wav" 2>/dev/null
fi

# Play audio
if [ "$BLOCKING" = "true" ]; then
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || true
    rm -f "$OUTFILE" 2>/dev/null || true
else
    # Background playback with cleanup
    (aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null; rm -f "$OUTFILE" 2>/dev/null) &
fi
