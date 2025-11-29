#!/bin/bash
# Jarvis Voice Assistant - Status Update TTS (Cloud/OpenAI)
# Lightweight TTS for short status messages during long tasks
# 
# Usage: say-status.sh "message" [blocking]
#   blocking: "true" (wait for playback) or "false" (background)

set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "cloud"

TEXT="${1:-}"
BLOCKING="${2:-true}"

if [ -z "$TEXT" ]; then
    echo "Usage: $0 <text to speak> [blocking]" >&2
    exit 1
fi

# Use temp file for status audio (short-lived)
OUTFILE="/tmp/jarvis-status-$$.wav"

# Build TTS JSON with same settings as main responses (consistent voice)
TTS_JSON=$(jq -n \
  --arg model "$TTS_MODEL" \
  --arg voice "$VOICE" \
  --arg input "$TEXT" \
  --arg instructions "$TTS_INSTRUCTIONS" \
  '{model:$model, voice:$voice, input:$input, instructions:$instructions}')

# Silence padding (ms) - helps speakers "wake up" before speech starts
SILENCE_PAD_MS="${STATUS_SILENCE_PAD_MS:-250}"

# Generate TTS audio
curl -s -X POST "https://api.openai.com/v1/audio/speech" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$TTS_JSON" \
  | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null

# Check if audio was generated
if [ ! -f "$OUTFILE" ] || [ ! -s "$OUTFILE" ]; then
    echo "⚠️ TTS generation failed" >&2
    exit 1
fi

# Add silence padding at the beginning (helps Bluetooth/wireless speakers wake up)
if command -v sox &>/dev/null && [ "$SILENCE_PAD_MS" -gt 0 ]; then
    PADDED_FILE="/tmp/jarvis-status-padded-$$.wav"
    # Convert ms to seconds for sox (e.g., 250ms = 0.25s)
    SILENCE_SECS=$(echo "scale=3; $SILENCE_PAD_MS / 1000" | bc)
    sox -n -r "$RATE" -c 2 -b 16 "/tmp/jarvis-silence-$$.wav" trim 0.0 "$SILENCE_SECS" 2>/dev/null
    sox "/tmp/jarvis-silence-$$.wav" "$OUTFILE" "$PADDED_FILE" 2>/dev/null
    mv "$PADDED_FILE" "$OUTFILE"
    rm -f "/tmp/jarvis-silence-$$.wav" 2>/dev/null
fi

# Play audio
if [ "$BLOCKING" = "true" ]; then
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || true
    rm -f "$OUTFILE" 2>/dev/null || true
else
    # Background playback with cleanup
    (aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null; rm -f "$OUTFILE" 2>/dev/null) &
fi

