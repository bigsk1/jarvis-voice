#!/bin/bash
# Jarvis Voice Assistant - Cloud TTS (OpenAI)
set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "cloud"

TEXT="$*"
if [ -z "$TEXT" ]; then
  echo "Usage: $0 <text to speak>" >&2
  exit 1
fi

OUTDIR="${AUDIO_DIR}/recordings"
mkdir -p "$OUTDIR"

# Timestamped filename
OUTFILE="$OUTDIR/tts-$(date +%F-%H%M%S).wav"

# Build TTS JSON safely with jq
TTS_JSON=$(jq -n \
  --arg model "$TTS_MODEL" \
  --arg voice "$VOICE" \
  --arg input "$TEXT" \
  --arg instructions "$TTS_INSTRUCTIONS" \
  '{model:$model, voice:$voice, input:$input, instructions:$instructions}')

# Call OpenAI TTS → decode with ffmpeg → save as proper WAV
curl -s -X POST "https://api.openai.com/v1/audio/speech" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$TTS_JSON" \
  | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"

# Add ~120ms of lead-in silence to avoid cut-ins
sox "$OUTFILE" -t wav "$OUTFILE.pad.wav" pad 0.2
mv "$OUTFILE.pad.wav" "$OUTFILE"

# Playback
aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || echo "⚠️ Playback failed" >&2

echo "✅ Saved and played: $OUTFILE"

