#!/bin/bash
# Jarvis Voice Assistant - Cloud TTS (OpenAI, ElevenLabs, xAI, Qwen3-TTS, or Kokoro URL)
# Loads config/cloud.env — uses TTS_PROVIDER from env.
#
# Examples:
#   ./bin/say.sh "Testing TTS on CLI"
#   ./bin/say.sh "The answer is forty-two"
set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
source "$SCRIPT_DIR/tts-common.sh"
load_config "cloud"

TEXT="$*"
if [ -z "$TEXT" ]; then
  echo "Usage: $0 <text to speak>" >&2
  exit 1
fi

OUTDIR="${AUDIO_DIR}/recordings"
mkdir -p "$OUTDIR"

# Timestamped filename
OUTFILE="$OUTDIR/tts-$(date +%F-%H%M%S)-$$.wav"

# Determine TTS provider (default to openai for backward compatibility)
# TTS_PROVIDER_OVERRIDE allows API calls to override the config file setting
TTS_PROVIDER="${TTS_PROVIDER_OVERRIDE:-${TTS_PROVIDER:-openai}}"

if [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
    # ============================================================================
    # QWEN3-TTS (Local network, OpenAI-compatible voice cloning)
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

elif [ "$TTS_PROVIDER" = "kokoro" ]; then
    # ============================================================================
    # Kokoro (OpenAI-compatible HTTP — same payload as jarvis-web / say-local URL mode)
    # ============================================================================
    KOKORO_URL="${KOKORO_TTS_URL:-}"
    KOKORO_VOICE="${KOKORO_TTS_VOICE:-af_nicole}"
    KOKORO_SPEED="${KOKORO_TTS_SPEED:-1.0}"

    if [ -z "$KOKORO_URL" ]; then
        echo "❌ KOKORO_TTS_URL not set in cloud.env (required for kokoro)" >&2
        exit 1
    fi

    TTS_JSON=$(jq -n \
      --arg model "kokoro" \
      --arg voice "$KOKORO_VOICE" \
      --arg input "$TEXT" \
      --arg speed "$KOKORO_SPEED" \
      '{model:$model, voice:$voice, input:$input, speed:($speed|tonumber)}')

    HTTP_CODE=$(curl -sS -w "%{http_code}" -o "$OUTFILE.raw" \
      -X POST "$KOKORO_URL" \
      -H "Content-Type: application/json" \
      -d "$TTS_JSON")

    if [ "$HTTP_CODE" != "200" ]; then
        echo "❌ Kokoro TTS API error (HTTP $HTTP_CODE)" >&2
        cat "$OUTFILE.raw" >&2
        rm -f "$OUTFILE.raw"
        exit 1
    fi

    ffmpeg -hide_banner -loglevel error -i "$OUTFILE.raw" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"
    rm -f "$OUTFILE.raw"

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
    
    # Get voice settings from config (with sensible defaults)
    ELEVENLABS_TTS_STABILITY="${ELEVENLABS_TTS_STABILITY:-0.5}"
    ELEVENLABS_TTS_SIMILARITY_BOOST="${ELEVENLABS_TTS_SIMILARITY_BOOST:-0.75}"
    ELEVENLABS_TTS_STYLE="${ELEVENLABS_TTS_STYLE:-0.5}"
    ELEVENLABS_TTS_USE_SPEAKER_BOOST="${ELEVENLABS_TTS_USE_SPEAKER_BOOST:-true}"
    
    # Build ElevenLabs TTS JSON
    # v3 has different voice_settings requirements (stability must be 0.0, 0.5, or 1.0)
    if [ "$ELEVENLABS_TTS_MODEL" = "eleven_v3" ]; then
        TTS_JSON=$(jq -n \
          --arg text "$TEXT" \
          --arg model_id "$ELEVENLABS_TTS_MODEL" \
          --argjson stability "$ELEVENLABS_TTS_STABILITY" \
          --argjson similarity "$ELEVENLABS_TTS_SIMILARITY_BOOST" \
          '{
            text: $text,
            model_id: $model_id,
            voice_settings: {
              stability: $stability,
              similarity_boost: $similarity
            }
          }')
    else
        TTS_JSON=$(jq -n \
          --arg text "$TEXT" \
          --arg model_id "$ELEVENLABS_TTS_MODEL" \
          --argjson stability "$ELEVENLABS_TTS_STABILITY" \
          --argjson similarity "$ELEVENLABS_TTS_SIMILARITY_BOOST" \
          --argjson style "$ELEVENLABS_TTS_STYLE" \
          --argjson speaker_boost "$ELEVENLABS_TTS_USE_SPEAKER_BOOST" \
          '{
            text: $text,
            model_id: $model_id,
            voice_settings: {
              stability: $stability,
              similarity_boost: $similarity,
              style: $style,
              use_speaker_boost: $speaker_boost
            }
          }')
    fi
    
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

elif [ "$TTS_PROVIDER" = "xai" ]; then
    # ============================================================================
    # xAI TTS
    # ============================================================================
    XAI_API_KEY="${XAI_API_KEY:-}"
    XAI_TTS_VOICE="${XAI_TTS_VOICE_OVERRIDE:-${XAI_TTS_VOICE:-eve}}"
    XAI_TTS_LANGUAGE="${XAI_TTS_LANGUAGE:-en}"
    XAI_TTS_CODEC="${XAI_TTS_CODEC:-mp3}"
    XAI_TTS_SAMPLE_RATE="${XAI_TTS_SAMPLE_RATE:-24000}"
    XAI_TTS_BIT_RATE="${XAI_TTS_BIT_RATE:-128000}"
    XAI_TTS_MAX_CHARS="${XAI_TTS_MAX_CHARS:-15000}"
    XAI_TTS_TIMEOUT="${XAI_TTS_TIMEOUT:-180}"

    if [ -z "$XAI_API_KEY" ]; then
        echo "❌ XAI_API_KEY not set in cloud.env" >&2
        exit 1
    fi

    XAI_TTS_TEXT="${TEXT:0:$XAI_TTS_MAX_CHARS}"

    TTS_JSON=$(jq -n \
      --arg text "$XAI_TTS_TEXT" \
      --arg voice_id "$XAI_TTS_VOICE" \
      --arg language "$XAI_TTS_LANGUAGE" \
      --arg codec "$XAI_TTS_CODEC" \
      --argjson sample_rate "$XAI_TTS_SAMPLE_RATE" \
      --argjson bit_rate "$XAI_TTS_BIT_RATE" \
      '{
        text: $text,
        voice_id: $voice_id,
        language: $language,
        output_format: (
          {codec: $codec, sample_rate: $sample_rate}
          + (if $codec == "mp3" then {bit_rate: $bit_rate} else {} end)
        )
      }')

    TEMP_AUDIO="/tmp/jarvis-tts-$$.${XAI_TTS_CODEC}"
    HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TEMP_AUDIO" \
      --connect-timeout 15 \
      --max-time "$XAI_TTS_TIMEOUT" \
      -X POST "https://api.x.ai/v1/tts" \
      -H "Authorization: Bearer $XAI_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$TTS_JSON")

    if [ "$HTTP_CODE" != "200" ]; then
        echo "❌ xAI TTS API error (HTTP $HTTP_CODE)" >&2
        cat "$TEMP_AUDIO" >&2
        rm -f "$TEMP_AUDIO"
        exit 1
    fi

    ffmpeg -hide_banner -loglevel error -i "$TEMP_AUDIO" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"
    rm -f "$TEMP_AUDIO"

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

    # Call OpenAI TTS and decode with ffmpeg into a proper WAV.
    TEMP_AUDIO="/tmp/jarvis-tts-openai-$$.raw"
    HTTP_CODE=$(curl -sS -w "%{http_code}" -o "$TEMP_AUDIO" \
      -X POST "https://api.openai.com/v1/audio/speech" \
      -H "Authorization: Bearer $OPENAI_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$TTS_JSON")

    if [ "$HTTP_CODE" != "200" ]; then
        echo "❌ OpenAI TTS API error (HTTP $HTTP_CODE)" >&2
        cat "$TEMP_AUDIO" >&2
        rm -f "$TEMP_AUDIO"
        exit 1
    fi

    ffmpeg -hide_banner -loglevel error -i "$TEMP_AUDIO" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE"
    rm -f "$TEMP_AUDIO"
fi

jarvis_tts_require_audio_file "$OUTFILE"

# Add ~120ms of lead-in silence to avoid cut-ins
sox "$OUTFILE" -t wav "$OUTFILE.pad.wav" pad 0.2
mv "$OUTFILE.pad.wav" "$OUTFILE"

# Playback
jarvis_tts_play_audio "$OUTFILE"

echo "✅ Saved and played: $OUTFILE (provider: $TTS_PROVIDER)"
