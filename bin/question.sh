#!/bin/bash
# Jarvis Voice Assistant - Cloud Q&A from text (OpenAI chat + OpenAI TTS)
# Loads config/cloud.env — STT/chat/TTS are hardcoded to OpenAI APIs in this script.
# For multi-provider TTS, use say.sh or question-orchestrator.sh instead.
#
# Examples:
#   ./bin/question.sh "What is the capital of France?"
#   ./bin/question.sh "Summarize today's news in one sentence"
set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "cloud"

QUESTION="${*:-}"
if [ -z "$QUESTION" ]; then
  echo "Usage: $0 <your question>" >&2
  exit 1
fi

OUTDIR="${AUDIO_DIR}/recordings"
mkdir -p "$OUTDIR" "${AUDIO_DIR}/logs"

STAMP="$(date +%F-%H%M%S)"
TXT_FILE="${AUDIO_DIR}/logs/qa-$STAMP.txt"
WAV_FILE="$OUTDIR/qa-$STAMP.wav"
TMP_MP3="/tmp/qa-$STAMP.mp3"

echo "🤖 Asking: $QUESTION"

# Build chat JSON without interpolating user/config text into JSON syntax.
CHAT_JSON=$(jq -n \
  --arg model "$OPENAI_MODEL" \
  --arg system "$SYSTEM_PROMPT" \
  --arg user "$QUESTION" \
  '{model:$model, messages:[{role:"system", content:$system}, {role:"user", content:$user}]}')

# Get text answer
ANSWER=$(curl -sS https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$CHAT_JSON" | jq -r '.choices[0].message.content // empty')

if [ -z "$ANSWER" ]; then
  echo "❌ No answer text from chat endpoint." >&2
  exit 1
fi

# Save text
echo "$ANSWER" | tee "$TXT_FILE"

# Build TTS JSON
TTS_JSON=$(jq -n \
  --arg model "$TTS_MODEL" \
  --arg voice "$VOICE" \
  --arg input "$ANSWER" \
  --arg instructions "$TTS_INSTRUCTIONS" \
  '{model:$model, voice:$voice, input:$input, instructions:$instructions}')

# Call TTS
curl -sS -o "$TMP_MP3" -X POST "https://api.openai.com/v1/audio/speech" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$TTS_JSON"

# Detect if JSON error
MIME_TYPE=$(file --mime-type -b "$TMP_MP3" || echo '')
if echo "$MIME_TYPE" | grep -qi 'application/json'; then
  echo "❌ OpenAI TTS returned an error JSON:" >&2
  cat "$TMP_MP3" >&2
  rm -f "$TMP_MP3"
  exit 1
fi

# Convert MP3 → WAV
ffmpeg -hide_banner -loglevel error -i "$TMP_MP3" -ar "$RATE" -ac 2 -f wav -y "$WAV_FILE"

# Add padding
sox "$WAV_FILE" -t wav "$WAV_FILE.pad.wav" pad 0.2
mv "$WAV_FILE.pad.wav" "$WAV_FILE"

# Play
aplay -D "$OUT_DEV" "$WAV_FILE" 2>/dev/null || {
  echo "⚠️ aplay failed. WAV saved at: $WAV_FILE" >&2
  rm -f "$TMP_MP3"
  exit 1
}

rm -f "$TMP_MP3"

echo "✅ Saved:"
echo "   Text:  $TXT_FILE"
echo "   Audio: $WAV_FILE"
