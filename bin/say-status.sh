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

# Play audio
if [ "$BLOCKING" = "true" ]; then
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || true
    rm -f "$OUTFILE" 2>/dev/null || true
else
    # Background playback with cleanup
    (aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null; rm -f "$OUTFILE" 2>/dev/null) &
fi

