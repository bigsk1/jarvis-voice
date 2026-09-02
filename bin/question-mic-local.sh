#!/bin/bash
# Jarvis Voice Assistant - Local Q&A from microphone
# Loads config/local.env — configured STT, then hands off to question-local.sh (Ollama + TTS_PROVIDER).
#
# Examples:
#   ./bin/question-mic-local.sh
#   # speak your question when prompted; local STT → Ollama → kokoro/qwen3-tts
set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"
START_THRESH="${START_THRESH:-${THRESH:-3%}}"
STOP_THRESH="${STOP_THRESH:-${THRESH:-5%}}"
MIC_HIGHPASS_HZ="${MIC_HIGHPASS_HZ:-300}"

OUTDIR="${AUDIO_DIR}"
MIC_DIR="$OUTDIR/mic"
mkdir -p "$MIC_DIR" "$OUTDIR/logs" "$OUTDIR/tts"

STAMP="$(date +%F-%H%M%S)"
RAW_WAV="$MIC_DIR/mic-$STAMP.wav"

echo "🎤 Speak your question… (auto-stops after ${POST_SIL}s silence or ${MAX_RECORD_TIME}s max)"

sox -t alsa "$IN_DEV" -r "$RATE" -c "$CHAN" -b 16 "$RAW_WAV" \
    trim 0 "$MAX_RECORD_TIME" \
    highpass "$MIC_HIGHPASS_HZ" \
    silence 1 "$PRE_SIL" "$START_THRESH" 1 "$POST_SIL" "$STOP_THRESH"

BYTES=$(stat -c%s "$RAW_WAV" || echo 0)
if [ "$BYTES" -lt 20000 ]; then
  echo "⚠️ Very short recording ($BYTES bytes). Try speaking louder/longer." >&2
  exit 1
fi

# Transcribe using the local-mode STT configuration
if ! TRANSCRIPT=$(python3 "$SCRIPT_DIR/stt.py" --mode local "$RAW_WAV"); then
  echo "❌ Transcription failed." >&2
  exit 1
fi
if [ -z "$TRANSCRIPT" ]; then
  echo "❌ STT returned empty text." >&2
  exit 1
fi

echo "🙋 You asked: $TRANSCRIPT"

# Hand off to local question flow
"$SCRIPT_DIR/question-local.sh" "$TRANSCRIPT"
