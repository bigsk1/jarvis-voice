#!/bin/bash
# Jarvis Voice Assistant - Local TTS (Kokoro)
set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"

TEXT="${*:-}"
if [ -z "$TEXT" ]; then
  echo "Usage: $0 <text to speak>" >&2
  exit 1
fi

OUTDIR="${AUDIO_DIR}/tts"
mkdir -p "$OUTDIR"
OUTFILE="$OUTDIR/tts-$(date +%F-%H%M%S).wav"

# Sanitize: collapse whitespace, strip control chars & emoji
SANITIZED=$(printf "%s" "$TEXT" \
  | tr -d '\000' \
  | tr '\r' '\n' \
  | sed 's/[[:cntrl:]]//g' \
  | sed 's/[[:space:]]\+/ /g' \
  | sed 's/^ *//;s/ *$//')

# Build JSON safely with jq
jq -n \
  --arg voice "$TTS_VOICE" \
  --arg input "$SANITIZED" \
  --arg speed "$TTS_SPEED" \
  '{voice:$voice, input:$input, speed:$speed}' \
| curl -sS -X POST "$TTS_URL" \
    -H "Content-Type: application/json" \
    -d @- \
| ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"

# Add ~120ms of lead-in silence to avoid cut-ins
sox "$OUTFILE" -t wav "$OUTFILE.pad.wav" pad 0.2
mv "$OUTFILE.pad.wav" "$OUTFILE"

aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || echo "⚠️ Playback failed" >&2
echo "✅ Saved and played: $OUTFILE"

