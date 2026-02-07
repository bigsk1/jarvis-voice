#!/bin/bash
# Jarvis Voice Assistant - Local TTS (Kokoro or Qwen3-TTS)
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

# Determine TTS provider (default to kokoro for backward compatibility)
# TTS_PROVIDER_OVERRIDE allows API calls to override the config file setting
TTS_PROVIDER="${TTS_PROVIDER_OVERRIDE:-${TTS_PROVIDER:-kokoro}}"

if [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
    # ============================================================================
    # QWEN3-TTS (OpenAI-compatible voice cloning)
    # ============================================================================
    QWEN3_TTS_URL="${QWEN3_TTS_URL:-http://localhost:8881/v1/audio/speech}"
    # QWEN3_TTS_VOICE_OVERRIDE allows API calls to specify a different voice
    QWEN3_TTS_VOICE="${QWEN3_TTS_VOICE_OVERRIDE:-${QWEN3_TTS_VOICE:-Jarvis}}"
    QWEN3_TTS_FORMAT="${QWEN3_TTS_FORMAT:-mp3}"
    QWEN3_TTS_SPEED="${QWEN3_TTS_SPEED:-1.0}"
    
    # Build OpenAI-compatible TTS JSON
    TTS_JSON=$(jq -n \
      --arg model "tts-1" \
      --arg voice "$QWEN3_TTS_VOICE" \
      --arg input "$SANITIZED" \
      --arg format "$QWEN3_TTS_FORMAT" \
      --arg speed "$QWEN3_TTS_SPEED" \
      '{model:$model, voice:$voice, input:$input, response_format:$format, speed:($speed|tonumber)}')
    
    # Call Qwen3-TTS API
    TEMP_AUDIO="/tmp/jarvis-tts-$$.${QWEN3_TTS_FORMAT}"
    HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TEMP_AUDIO" \
      -X POST "$QWEN3_TTS_URL" \
      -H "Content-Type: application/json" \
      -d "$TTS_JSON")
    
    if [ "$HTTP_CODE" != "200" ]; then
        echo "❌ Qwen3-TTS API error (HTTP $HTTP_CODE)" >&2
        cat "$TEMP_AUDIO" >&2
        rm -f "$TEMP_AUDIO"
        exit 1
    fi
    
    # Convert to wav with proper format
    ffmpeg -hide_banner -loglevel error -i "$TEMP_AUDIO" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"
    rm -f "$TEMP_AUDIO"
    
else
    # ============================================================================
    # KOKORO TTS (default - legacy format)
    # ============================================================================
    # Support both new and legacy variable names
    KOKORO_URL="${KOKORO_TTS_URL:-${TTS_URL:-}}"
    KOKORO_VOICE="${KOKORO_TTS_VOICE:-${TTS_VOICE:-af_nicole}}"
    KOKORO_SPEED="${KOKORO_TTS_SPEED:-${TTS_SPEED:-1.0}}"
    
    if [ -z "$KOKORO_URL" ]; then
        echo "❌ TTS_URL or KOKORO_TTS_URL not set in local.env" >&2
        exit 1
    fi
    
    # Build Kokoro JSON
    TTS_JSON=$(jq -n \
      --arg voice "$KOKORO_VOICE" \
      --arg input "$SANITIZED" \
      --arg speed "$KOKORO_SPEED" \
      '{voice:$voice, input:$input, speed:$speed}')
    
    # Call Kokoro TTS API
    curl -sS -X POST "$KOKORO_URL" \
        -H "Content-Type: application/json" \
        -d "$TTS_JSON" \
    | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"
fi

# Add ~120ms of lead-in silence to avoid cut-ins
sox "$OUTFILE" -t wav "$OUTFILE.pad.wav" pad 0.2
mv "$OUTFILE.pad.wav" "$OUTFILE"

aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || echo "⚠️ Playback failed" >&2
echo "✅ Saved and played: $OUTFILE (provider: $TTS_PROVIDER)"
