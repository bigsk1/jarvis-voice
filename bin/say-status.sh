#!/bin/bash
# Jarvis Voice Assistant - Status Update TTS (Cloud - OpenAI, ElevenLabs, xAI, Qwen3-TTS, or Kokoro URL)
# Lightweight TTS for short status messages during long tasks
# 
# Features:
# - Audio caching: Repeated phrases play instantly (no API call)
# - Silence padding: Helps speakers wake up before speech
# - Cloud provider support: OpenAI, ElevenLabs, xAI, Qwen3-TTS, Kokoro (HTTP)
# 
# Usage: say-status.sh "message" [blocking]
#   blocking: "true" (wait for playback) or "false" (background)
#
# Examples:
#   ./bin/say-status.sh "Working on it"
#   ./bin/say-status.sh "Still thinking" false

set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
source "$SCRIPT_DIR/tts-common.sh"
load_config "cloud"

TEXT="${1:-}"
BLOCKING="${2:-true}"

if [ -z "$TEXT" ]; then
    echo "Usage: $0 <text to speak> [blocking]" >&2
    exit 1
fi

# Determine TTS provider (default to openai for backward compatibility)
TTS_PROVIDER="${TTS_PROVIDER:-openai}"

# ============================================================================
# CACHING SYSTEM
# ============================================================================
# Cache key = hash of (text + voice settings + provider) so changes invalidate cache
STATUS_CACHE_ENABLED="${STATUS_CACHE_ENABLED:-true}"
CACHE_DIR="${HOME}/.cache/jarvis/status-tts"
SILENCE_PAD_MS="${STATUS_SILENCE_PAD_MS:-250}"
STATUS_ELEVENLABS_TTS_MODEL="${ELEVENLABS_STATUS_TTS_MODEL:-${ELEVENLABS_TTS_MODEL:-}}"
STATUS_TTS_CONNECT_TIMEOUT="${STATUS_TTS_CONNECT_TIMEOUT:-15}"
STATUS_TTS_TIMEOUT="${STATUS_TTS_TIMEOUT:-25}"

# Create cache dir if caching enabled
if [ "$STATUS_CACHE_ENABLED" = "true" ]; then
    mkdir -p "$CACHE_DIR"
fi

# Generate cache key from text + voice settings + provider
# Any setting change = new cache key = new audio generation
generate_cache_key() {
    local text="$1"
    if [ "$TTS_PROVIDER" = "elevenlabs" ]; then
        # Hash only voice settings that are actually sent for the effective model.
        local eleven_key="${text}|elevenlabs|${ELEVENLABS_TTS_VOICE:-}|${STATUS_ELEVENLABS_TTS_MODEL}|${ELEVENLABS_TTS_STABILITY:-0.5}|${ELEVENLABS_TTS_SIMILARITY_BOOST:-0.75}"
        if [ "$STATUS_ELEVENLABS_TTS_MODEL" != "eleven_v3" ]; then
            eleven_key="${eleven_key}|${ELEVENLABS_TTS_STYLE:-0.5}|${ELEVENLABS_TTS_USE_SPEAKER_BOOST:-true}"
        fi
        echo -n "${eleven_key}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    elif [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
        # Include Qwen3-TTS settings in hash
        echo -n "${text}|qwen3-tts|${QWEN3_TTS_VOICE:-Jarvis}|${QWEN3_TTS_SPEED:-1.0}|${QWEN3_TTS_FORMAT:-mp3}|${QWEN3_TTS_URL:-http://localhost:8881/v1/audio/speech}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    elif [ "$TTS_PROVIDER" = "xai" ]; then
        # Include xAI TTS settings in hash
        echo -n "${text}|xai|${XAI_TTS_VOICE:-eve}|${XAI_TTS_LANGUAGE:-en}|${XAI_TTS_CODEC:-mp3}|${XAI_TTS_SAMPLE_RATE:-24000}|${XAI_TTS_BIT_RATE:-128000}|${XAI_TTS_MAX_CHARS:-5000}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    elif [ "$TTS_PROVIDER" = "kokoro" ]; then
        echo -n "${text}|kokoro|${KOKORO_TTS_VOICE:-af_nicole}|${KOKORO_TTS_SPEED:-1.0}|${KOKORO_TTS_URL:-}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    else
        # Include OpenAI settings in hash
        echo -n "${text}|openai|${VOICE}|${TTS_MODEL}|${TTS_INSTRUCTIONS:-}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    fi
}

CACHE_KEY=$(generate_cache_key "$TEXT")
CACHED_FILE="$CACHE_DIR/${CACHE_KEY}.wav"

# Check cache first
if [ "$STATUS_CACHE_ENABLED" = "true" ] && [ -f "$CACHED_FILE" ] && [ -s "$CACHED_FILE" ]; then
    # Cache hit! Play directly (instant, no API call)
    OUTFILE="$CACHED_FILE"
else
    # Cache miss - generate TTS
    OUTFILE="/tmp/jarvis-status-$$.wav"

    if [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
        # ============================================================================
        # QWEN3-TTS (Local network, OpenAI-compatible voice cloning)
        # ============================================================================
        QWEN3_TTS_URL="${QWEN3_TTS_URL:-http://localhost:8881/v1/audio/speech}"
        QWEN3_TTS_VOICE="${QWEN3_TTS_VOICE:-Jarvis}"
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
        TEMP_AUDIO="/tmp/jarvis-status-$$.${QWEN3_TTS_FORMAT}"
        if ! HTTP_CODE=$(jarvis_tts_http_to_file "Qwen3-TTS" "$TEMP_AUDIO" \
          "$STATUS_TTS_CONNECT_TIMEOUT" "$STATUS_TTS_TIMEOUT" \
          -X POST "$QWEN3_TTS_URL" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON"); then
            exit 1
        fi
        
        if [ "$HTTP_CODE" != "200" ]; then
            echo "⚠️ Qwen3-TTS failed (HTTP $HTTP_CODE)" >&2
            rm -f "$TEMP_AUDIO"
            exit 1
        fi
        
        # Convert to wav
        ffmpeg -hide_banner -loglevel error -i "$TEMP_AUDIO" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null
        rm -f "$TEMP_AUDIO"
        
    elif [ "$TTS_PROVIDER" = "elevenlabs" ]; then
        # ============================================================================
        # ELEVENLABS TTS
        # ============================================================================
        ELEVENLABS_API_KEY="${ELEVENLABS_API_KEY:-}"
        ELEVENLABS_TTS_VOICE="${ELEVENLABS_TTS_VOICE:-pgCnBQgKPGkIP8fJuita}"
        ELEVENLABS_TTS_MODEL="${STATUS_ELEVENLABS_TTS_MODEL:-eleven_multilingual_v2}"
        
        if [ -z "$ELEVENLABS_API_KEY" ]; then
            echo "❌ ELEVENLABS_API_KEY not set" >&2
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
        
        # Call ElevenLabs TTS API
        TEMP_MP3="/tmp/jarvis-status-$$.mp3"
        if ! HTTP_CODE=$(jarvis_tts_http_to_file "ElevenLabs TTS" "$TEMP_MP3" \
          "$STATUS_TTS_CONNECT_TIMEOUT" "$STATUS_TTS_TIMEOUT" \
          -X POST "https://api.elevenlabs.io/v1/text-to-speech/${ELEVENLABS_TTS_VOICE}" \
          -H "xi-api-key: $ELEVENLABS_API_KEY" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON"); then
            exit 1
        fi
        
        if [ "$HTTP_CODE" != "200" ]; then
            echo "⚠️ ElevenLabs TTS failed (HTTP $HTTP_CODE)" >&2
            rm -f "$TEMP_MP3"
            exit 1
        fi
        
        # Convert mp3 to wav
        ffmpeg -hide_banner -loglevel error -i "$TEMP_MP3" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null
        rm -f "$TEMP_MP3"
    elif [ "$TTS_PROVIDER" = "xai" ]; then
        # ============================================================================
        # xAI TTS
        # ============================================================================
        XAI_API_KEY="${XAI_API_KEY:-}"
        XAI_TTS_VOICE="${XAI_TTS_VOICE:-eve}"
        XAI_TTS_LANGUAGE="${XAI_TTS_LANGUAGE:-en}"
        XAI_TTS_CODEC="${XAI_TTS_CODEC:-mp3}"
        XAI_TTS_SAMPLE_RATE="${XAI_TTS_SAMPLE_RATE:-24000}"
        XAI_TTS_BIT_RATE="${XAI_TTS_BIT_RATE:-128000}"
        XAI_TTS_MAX_CHARS="${XAI_TTS_MAX_CHARS:-5000}"

        if [ -z "$XAI_API_KEY" ]; then
            echo "❌ XAI_API_KEY not set" >&2
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

        TEMP_AUDIO="/tmp/jarvis-status-$$.${XAI_TTS_CODEC}"
        if ! HTTP_CODE=$(jarvis_tts_http_to_file "xAI TTS" "$TEMP_AUDIO" \
          "$STATUS_TTS_CONNECT_TIMEOUT" "$STATUS_TTS_TIMEOUT" \
          -X POST "https://api.x.ai/v1/tts" \
          -H "Authorization: Bearer $XAI_API_KEY" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON"); then
            exit 1
        fi

        if [ "$HTTP_CODE" != "200" ]; then
            echo "⚠️ xAI TTS failed (HTTP $HTTP_CODE)" >&2
            rm -f "$TEMP_AUDIO"
            exit 1
        fi

        ffmpeg -hide_banner -loglevel error -i "$TEMP_AUDIO" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null
        rm -f "$TEMP_AUDIO"
    elif [ "$TTS_PROVIDER" = "kokoro" ]; then
        KOKORO_URL="${KOKORO_TTS_URL:-}"
        KOKORO_VOICE="${KOKORO_TTS_VOICE:-af_nicole}"
        KOKORO_SPEED="${KOKORO_TTS_SPEED:-1.0}"

        if [ -z "$KOKORO_URL" ]; then
            echo "⚠️ KOKORO_TTS_URL not set for kokoro" >&2
            exit 1
        fi

        TTS_JSON=$(jq -n \
          --arg model "kokoro" \
          --arg voice "$KOKORO_VOICE" \
          --arg input "$TEXT" \
          --arg speed "$KOKORO_SPEED" \
          '{model:$model, voice:$voice, input:$input, speed:($speed|tonumber)}')

        TEMP_RAW="/tmp/jarvis-status-kokoro-$$.rawaudio"
        if ! HTTP_CODE=$(jarvis_tts_http_to_file "Kokoro TTS" "$TEMP_RAW" \
          "$STATUS_TTS_CONNECT_TIMEOUT" "$STATUS_TTS_TIMEOUT" \
          -X POST "$KOKORO_URL" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON"); then
            exit 1
        fi

        if [ "$HTTP_CODE" != "200" ]; then
            echo "⚠️ Kokoro TTS failed (HTTP $HTTP_CODE)" >&2
            rm -f "$TEMP_RAW"
            exit 1
        fi

        ffmpeg -hide_banner -loglevel error -i "$TEMP_RAW" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null
        rm -f "$TEMP_RAW"
    else
        # ============================================================================
        # OPENAI TTS (default)
        # ============================================================================
        # Build TTS JSON with same settings as main responses (consistent voice)
        TTS_JSON=$(jq -n \
          --arg model "$TTS_MODEL" \
          --arg voice "$VOICE" \
          --arg input "$TEXT" \
          --arg instructions "$TTS_INSTRUCTIONS" \
          '{model:$model, voice:$voice, input:$input, instructions:$instructions}')

        # Generate TTS audio with bounded network waits and explicit HTTP errors.
        TEMP_AUDIO="/tmp/jarvis-status-openai-$$.raw"
        if ! HTTP_CODE=$(jarvis_tts_http_to_file "OpenAI TTS" "$TEMP_AUDIO" \
          "$STATUS_TTS_CONNECT_TIMEOUT" "$STATUS_TTS_TIMEOUT" \
          -X POST "https://api.openai.com/v1/audio/speech" \
          -H "Authorization: Bearer $OPENAI_API_KEY" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON"); then
            exit 1
        fi

        if [ "$HTTP_CODE" != "200" ]; then
            echo "⚠️ OpenAI TTS failed (HTTP $HTTP_CODE)" >&2
            rm -f "$TEMP_AUDIO"
            exit 1
        fi

        if ! ffmpeg -hide_banner -loglevel error -i "$TEMP_AUDIO" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null; then
            echo "⚠️ OpenAI TTS audio decode failed" >&2
            rm -f "$TEMP_AUDIO"
            exit 1
        fi
        rm -f "$TEMP_AUDIO"
    fi

    # Check if audio was generated
    if [ ! -f "$OUTFILE" ] || [ ! -s "$OUTFILE" ]; then
        echo "⚠️ TTS generation failed" >&2
        exit 1
    fi

    # Add silence padding at the beginning (helps Bluetooth/wireless speakers wake up)
    if command -v sox &>/dev/null && [ "$SILENCE_PAD_MS" -gt 0 ]; then
        PADDED_FILE="/tmp/jarvis-status-padded-$$.wav"
        # Convert ms to seconds for sox (e.g., 250ms = 0.25s)
        SILENCE_SECS=$(echo "scale=3; $SILENCE_PAD_MS / 1000" | bc)
        sox -n -r "$RATE" -c 2 -b 16 "/tmp/jarvis-silence-$$.wav" trim 0.0 "$SILENCE_SECS" 2>/dev/null
        sox "/tmp/jarvis-silence-$$.wav" "$OUTFILE" "$PADDED_FILE" 2>/dev/null
        mv "$PADDED_FILE" "$OUTFILE"
        rm -f "/tmp/jarvis-silence-$$.wav" 2>/dev/null
    fi

    # Save to cache if enabled
    if [ "$STATUS_CACHE_ENABLED" = "true" ]; then
        cp "$OUTFILE" "$CACHED_FILE"
    fi
fi

# Play audio
if [ "$BLOCKING" = "true" ]; then
    if jarvis_tts_play_audio "$OUTFILE"; then
        PLAYBACK_STATUS=0
    else
        PLAYBACK_STATUS=$?
    fi
    # Only delete temp files, not cached files
    if [[ "$OUTFILE" == /tmp/* ]]; then
        rm -f "$OUTFILE" 2>/dev/null || true
    fi
    exit "$PLAYBACK_STATUS"
else
    # Background playback with cleanup (only temp files)
    if [[ "$OUTFILE" == /tmp/* ]]; then
        (jarvis_tts_play_audio "$OUTFILE" || true; rm -f "$OUTFILE" 2>/dev/null) &
    else
        (jarvis_tts_play_audio "$OUTFILE" || true) &
    fi
fi
