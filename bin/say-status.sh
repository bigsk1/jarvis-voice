#!/bin/bash
# Jarvis Voice Assistant - Status Update TTS (Cloud - OpenAI or ElevenLabs)
# Lightweight TTS for short status messages during long tasks
# 
# Features:
# - Audio caching: Repeated phrases play instantly (no API call)
# - Silence padding: Helps speakers wake up before speech
# - Dual provider support: OpenAI or ElevenLabs
# 
# Usage: say-status.sh "message" [blocking]
#   blocking: "true" (wait for playback) or "false" (background)

set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
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

# Create cache dir if caching enabled
if [ "$STATUS_CACHE_ENABLED" = "true" ]; then
    mkdir -p "$CACHE_DIR"
fi

# Generate cache key from text + voice settings + provider
generate_cache_key() {
    local text="$1"
    if [ "$TTS_PROVIDER" = "elevenlabs" ]; then
        # Include ElevenLabs settings in hash
        echo -n "${text}|elevenlabs|${ELEVENLABS_TTS_VOICE:-}|${ELEVENLABS_TTS_MODEL:-}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    elif [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
        # Include Qwen3-TTS settings in hash
        echo -n "${text}|qwen3-tts|${QWEN3_TTS_VOICE:-Jarvis}|${QWEN3_TTS_FORMAT:-mp3}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    else
        # Include OpenAI settings in hash
        echo -n "${text}|openai|${VOICE}|${TTS_MODEL}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
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
        QWEN3_TTS_URL="${QWEN3_TTS_URL:-http://192.168.70.226:8881/v1/audio/speech}"
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
        HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TEMP_AUDIO" \
          -X POST "$QWEN3_TTS_URL" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON")
        
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
        ELEVENLABS_TTS_MODEL="${ELEVENLABS_TTS_MODEL:-eleven_multilingual_v2}"
        
        if [ -z "$ELEVENLABS_API_KEY" ]; then
            echo "❌ ELEVENLABS_API_KEY not set" >&2
            exit 1
        fi
        
        # Build ElevenLabs TTS JSON
        # v3 has different voice_settings requirements (stability must be 0.0, 0.5, or 1.0)
        if [ "$ELEVENLABS_TTS_MODEL" = "eleven_v3" ]; then
            TTS_JSON=$(jq -n \
              --arg text "$TEXT" \
              --arg model_id "$ELEVENLABS_TTS_MODEL" \
              '{
                text: $text,
                model_id: $model_id,
                voice_settings: {
                  stability: 0.5,
                  similarity_boost: 0.75
                }
              }')
        else
            TTS_JSON=$(jq -n \
              --arg text "$TEXT" \
              --arg model_id "$ELEVENLABS_TTS_MODEL" \
              '{
                text: $text,
                model_id: $model_id,
                voice_settings: {
                  stability: 0.5,
                  similarity_boost: 0.75,
                  style: 0.0,
                  use_speaker_boost: true
                }
              }')
        fi
        
        # Call ElevenLabs TTS API
        TEMP_MP3="/tmp/jarvis-status-$$.mp3"
        HTTP_CODE=$(curl -s -w "%{http_code}" -o "$TEMP_MP3" \
          -X POST "https://api.elevenlabs.io/v1/text-to-speech/${ELEVENLABS_TTS_VOICE}" \
          -H "xi-api-key: $ELEVENLABS_API_KEY" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON")
        
        if [ "$HTTP_CODE" != "200" ]; then
            echo "⚠️ ElevenLabs TTS failed (HTTP $HTTP_CODE)" >&2
            rm -f "$TEMP_MP3"
            exit 1
        fi
        
        # Convert mp3 to wav
        ffmpeg -hide_banner -loglevel error -i "$TEMP_MP3" -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null
        rm -f "$TEMP_MP3"
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

        # Generate TTS audio
        curl -s -X POST "https://api.openai.com/v1/audio/speech" \
          -H "Authorization: Bearer $OPENAI_API_KEY" \
          -H "Content-Type: application/json" \
          -d "$TTS_JSON" \
          | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null
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
    aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null || true
    # Only delete temp files, not cached files
    if [[ "$OUTFILE" == /tmp/* ]]; then
        rm -f "$OUTFILE" 2>/dev/null || true
    fi
else
    # Background playback with cleanup (only temp files)
    if [[ "$OUTFILE" == /tmp/* ]]; then
        (aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null; rm -f "$OUTFILE" 2>/dev/null) &
    else
        (aplay -D "$OUT_DEV" "$OUTFILE" 2>/dev/null) &
    fi
fi
