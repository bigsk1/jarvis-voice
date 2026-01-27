#!/bin/bash
# Jarvis Voice Assistant - Cloud TTS (OpenAI or ElevenLabs)
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

# Determine TTS provider (default to openai for backward compatibility)
# TTS_PROVIDER_OVERRIDE allows API calls to override the config file setting
TTS_PROVIDER="${TTS_PROVIDER_OVERRIDE:-${TTS_PROVIDER:-openai}}"

if [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
    # ============================================================================
    # QWEN3-TTS (Local network, OpenAI-compatible voice cloning)
    # ============================================================================
    QWEN3_TTS_URL="${QWEN3_TTS_URL:-http://192.168.70.226:8881/v1/audio/speech}"
    # QWEN3_TTS_VOICE_OVERRIDE allows API calls to specify a different voice
    QWEN3_TTS_VOICE="${QWEN3_TTS_VOICE_OVERRIDE:-${QWEN3_TTS_VOICE:-Jarvis}}"
    QWEN3_TTS_FORMAT="${QWEN3_TTS_FORMAT:-mp3}"
    QWEN3_TTS_SPEED="${QWEN3_TTS_SPEED:-1.0}"
    
    # Build OpenAI-compatible TTS JSON
    TTS_JSON=$(jq -n \
      --arg model "tts-1" \
      --arg voice "$QWEN3_TTS_VOICE" \
      --arg input "$TEXT" \
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

elif [ "$TTS_PROVIDER" = "elevenlabs" ]; then
    # ============================================================================
    # ELEVENLABS TTS
    # ============================================================================
    ELEVENLABS_API_KEY="${ELEVENLABS_API_KEY:-}"
    # ELEVENLABS_TTS_VOICE_OVERRIDE allows API calls to specify a different voice
    ELEVENLABS_TTS_VOICE="${ELEVENLABS_TTS_VOICE_OVERRIDE:-${ELEVENLABS_TTS_VOICE:-pgCnBQgKPGkIP8fJuita}}"
    ELEVENLABS_TTS_MODEL="${ELEVENLABS_TTS_MODEL:-eleven_multilingual_v2}"
    
    if [ -z "$ELEVENLABS_API_KEY" ]; then
        echo "❌ ELEVENLABS_API_KEY not set in cloud.env" >&2
        exit 1
    fi
    
    # Build ElevenLabs TTS JSON
    TTS_JSON=$(jq -n \
      --arg text "$TEXT" \
      --arg model_id "$ELEVENLABS_TTS_MODEL" \
      '{
        text: $text,
        model_id: $model_id,
        voice_settings: {
          stability: 0.7,
          similarity_boost: 0.75,
          style: 0.5,
          use_speaker_boost: true
        }
      }')
    
    # Call ElevenLabs TTS API (returns mp3 by default)
    TEMP_MP3="/tmp/jarvis-tts-$$.mp3"
    HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TEMP_MP3" \
      -X POST "https://api.elevenlabs.io/v1/text-to-speech/${ELEVENLABS_TTS_VOICE}" \
      -H "xi-api-key: $ELEVENLABS_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$TTS_JSON")
    
    if [ "$HTTP_CODE" != "200" ]; then
        echo "❌ ElevenLabs API error (HTTP $HTTP_CODE)" >&2
        cat "$TEMP_MP3" >&2  # Show error message
        rm -f "$TEMP_MP3"
        exit 1
    fi
    
    # Convert mp3 to wav with proper format
    ffmpeg -hide_banner -loglevel error -i "$TEMP_MP3" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"
    rm -f "$TEMP_MP3"

else
    # ============================================================================
    # OPENAI TTS (default)
    # ============================================================================
    # OPENAI_VOICE_OVERRIDE allows API calls to specify a different voice
    VOICE="${OPENAI_VOICE_OVERRIDE:-${VOICE:-alloy}}"
    
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
fi

# Add ~120ms of lead-in silence to avoid cut-ins
sox "$OUTFILE" -t wav "$OUTFILE.pad.wav" pad 0.2
mv "$OUTFILE.pad.wav" "$OUTFILE"

# Playback
aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || echo "⚠️ Playback failed" >&2

echo "✅ Saved and played: $OUTFILE (provider: $TTS_PROVIDER)"
