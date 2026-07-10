#!/bin/bash
# Jarvis Voice Assistant - Local Q&A from microphone
# Loads config/local.env — local STT, then hands off to question-local.sh (Ollama + TTS_PROVIDER).
#
# Examples:
#   ./bin/question-mic-local.sh
#   # speak your question when prompted; local STT → Ollama → kokoro/qwen3-tts
set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"

OUTDIR="${AUDIO_DIR}"
MIC_DIR="$OUTDIR/mic"
mkdir -p "$MIC_DIR" "$OUTDIR/logs" "$OUTDIR/tts"

STAMP="$(date +%F-%H%M%S)"
RAW_WAV="$MIC_DIR/mic-$STAMP.wav"

echo "🎤 Speak your question… (auto-stops after ${POST_SIL}s silence or ${MAX_RECORD_TIME}s max)"

sox -t alsa "$IN_DEV" -r "$RATE" -c "$CHAN" -b 16 "$RAW_WAV" \
    trim 0 "$MAX_RECORD_TIME" \
    highpass 300 \
    silence 1 "$PRE_SIL" "3%" 1 "$POST_SIL" "5%"

BYTES=$(stat -c%s "$RAW_WAV" || echo 0)
if [ "$BYTES" -lt 20000 ]; then
  echo "⚠️ Very short recording ($BYTES bytes). Try speaking louder/longer." >&2
  exit 1
fi

# Transcribe locally
TRANSCRIPT=$("$SCRIPT_DIR/stt-local.py" "$RAW_WAV" || true)
if [ -z "$TRANSCRIPT" ]; then
  echo "❌ Local STT returned empty text." >&2
  exit 1
fi

echo "🙋 You asked: $TRANSCRIPT"

# Hand off to local question flow
"$SCRIPT_DIR/question-local.sh" "$TRANSCRIPT"

