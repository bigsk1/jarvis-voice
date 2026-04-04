#!/bin/bash
# Jarvis Voice Assistant - Cloud Q&A from microphone
set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "cloud"
TTS_NORMALIZE="$SCRIPT_DIR/tts-normalize.py"

OUTDIR="${AUDIO_DIR}/mic"
mkdir -p "$OUTDIR" "${AUDIO_DIR}/recordings" "${AUDIO_DIR}/logs"

STAMP="$(date +%F-%H%M%S)"
RAW_WAV="$OUTDIR/mic-$STAMP.wav"
TXT_FILE="${AUDIO_DIR}/logs/qa-$STAMP.txt"
ANS_WAV="${AUDIO_DIR}/recordings/qa-$STAMP.wav"
TMP_MP3="/tmp/qa-$STAMP.mp3"

echo "🎤 Speak your question… (auto-stops after ${POST_SIL}s silence or ${MAX_RECORD_TIME}s max)"

# Record with SoX
sox -t alsa "$IN_DEV" -r "$RATE" -c "$CHAN" -b 16 "$RAW_WAV" \
    trim 0 "$MAX_RECORD_TIME" \
    highpass 300 \
    silence 1 "$PRE_SIL" "3%" 1 "$POST_SIL" "5%"

# Check file size
BYTES=$(stat -c%s "$RAW_WAV" || echo 0)
if [ "$BYTES" -lt 20000 ]; then
  echo "⚠️ Very short recording ($BYTES bytes). Try speaking louder/longer." >&2
  exit 1
fi

echo "📝 Transcribing…"
QUESTION=$(
  curl -sS https://api.openai.com/v1/audio/transcriptions \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -H "Content-Type: multipart/form-data" \
    -F "file=@$RAW_WAV" \
    -F "model=$STT_MODEL" \
  | jq -r '.text // empty'
)

if [ -z "$QUESTION" ]; then
  echo "❌ Transcription failed or empty." >&2
  exit 1
fi

echo "🙋 You asked: $QUESTION"
echo "$QUESTION" > "$TXT_FILE"

echo "🤖 Getting answer…"

ANSWER=$(
  curl -sS https://api.openai.com/v1/chat/completions \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"$OPENAI_MODEL\",
      \"messages\": [
        {\"role\":\"system\",\"content\":\"$SYSTEM_PROMPT\"},
        {\"role\":\"user\",\"content\":\"$QUESTION\"}
      ]
    }" \
  | jq -r '.choices[0].message.content // empty'
)

if [ -z "$ANSWER" ]; then
  echo "❌ Chat completion returned no answer." >&2
  exit 1
fi

ANSWER=$(python3 "$TTS_NORMALIZE" "$ANSWER")
if [ -z "$ANSWER" ]; then
  ANSWER="Done. I shared the details in chat."
fi

echo "🗣️ Speaking the answer (and saving files)…"

# Build TTS JSON
TTS_JSON=$(jq -n \
  --arg model "$TTS_MODEL" \
  --arg voice "$VOICE" \
  --arg input "$ANSWER" \
  --arg instructions "$TTS_INSTRUCTIONS" \
  '{model:$model, voice:$voice, input:$input, instructions:$instructions}')

curl -sS -o "$TMP_MP3" -X POST "https://api.openai.com/v1/audio/speech" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$TTS_JSON"

# Check if API returned JSON error
if file --mime-type -b "$TMP_MP3" | grep -qi json; then
  echo "❌ TTS error response:" >&2
  cat "$TMP_MP3" >&2
  rm -f "$TMP_MP3"
  exit 1
fi

# Convert MP3 → WAV
ffmpeg -hide_banner -loglevel error -i "$TMP_MP3" -ar "$RATE" -ac 2 -f wav -y "$ANS_WAV"

# Add padding
sox "$ANS_WAV" -t wav "$ANS_WAV.pad.wav" pad 0.2
mv "$ANS_WAV.pad.wav" "$ANS_WAV"

aplay -D "$OUT_DEV" "$ANS_WAV" 2>/dev/null || echo "⚠️ aplay failed; WAV saved at $ANS_WAV" >&2

rm -f "$TMP_MP3"

echo "✅ Saved:"
echo "   Your question text : $TXT_FILE"
echo "   Your question audio: $RAW_WAV"
echo "   Answer audio       : $ANS_WAV"
