#!/bin/bash
# Jarvis Voice Assistant - Status Update TTS (Local - Kokoro or Qwen3-TTS)
# Lightweight TTS for local mode status messages
#
# Features:
# - Audio caching: Repeated phrases play instantly (no TTS call)
# - Silence padding: Helps speakers wake up before speech
# - Dual provider support: Kokoro or Qwen3-TTS
#
# Usage: say-status-local.sh "message" [blocking]
#   blocking: "true" (wait for playback) or "false" (background)
#
# Examples:
#   ./bin/say-status-local.sh "Working on it"
#   ./bin/say-status-local.sh "Still thinking" false

set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
source "$SCRIPT_DIR/tts-common.sh"
load_config "local"

TEXT="${1:-}"
BLOCKING="${2:-true}"

if [ -z "$TEXT" ]; then
    echo "Usage: $0 <text to speak> [blocking]" >&2
    exit 1
fi

# Determine TTS provider (default to kokoro for backward compatibility)
TTS_PROVIDER="${TTS_PROVIDER:-kokoro}"

# ============================================================================
# CACHING SYSTEM
# ============================================================================
# Cache key = hash of (text + voice settings + provider) so changes invalidate cache
STATUS_CACHE_ENABLED="${STATUS_CACHE_ENABLED:-true}"
CACHE_DIR="${HOME}/.cache/jarvis/status-tts-local"
SILENCE_PAD_MS="${STATUS_SILENCE_PAD_MS:-250}"

# Create cache dir if caching enabled
if [ "$STATUS_CACHE_ENABLED" = "true" ]; then
    mkdir -p "$CACHE_DIR"
fi

# Generate cache key from text + voice settings + provider
generate_cache_key() {
    local text="$1"
    if [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
        echo -n "${text}|qwen3-tts|${QWEN3_TTS_VOICE:-Jarvis}|${QWEN3_TTS_SPEED:-1.0}|${QWEN3_TTS_FORMAT:-mp3}|${QWEN3_TTS_URL:-http://localhost:8881/v1/audio/speech}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    else
        # Kokoro
        local voice="${KOKORO_TTS_VOICE:-af_nicole}"
        local speed="${KOKORO_TTS_SPEED:-1.0}"
        echo -n "${text}|kokoro|${voice}|${speed}|${KOKORO_TTS_URL:-}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
    fi
}

CACHE_KEY=$(generate_cache_key "$TEXT")
CACHED_FILE="$CACHE_DIR/${CACHE_KEY}.wav"

# Check cache first
if [ "$STATUS_CACHE_ENABLED" = "true" ] && [ -f "$CACHED_FILE" ] && [ -s "$CACHED_FILE" ]; then
    # Cache hit! Play directly (instant, no TTS call)
    OUTFILE="$CACHED_FILE"
else
    # Cache miss - generate TTS
    OUTFILE="/tmp/jarvis-status-local-$$.wav"

    # Sanitize: collapse whitespace, strip control chars
    SANITIZED=$(printf "%s" "$TEXT" \
      | tr -d '\000' \
      | tr '\r' '\n' \
      | sed 's/[[:cntrl:]]//g' \
      | sed 's/[[:space:]]\+/ /g' \
      | sed 's/^ *//;s/ *$//')

    if [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
        # ============================================================================
        # QWEN3-TTS (OpenAI-compatible voice cloning)
        # ============================================================================
        QWEN3_TTS_URL="${QWEN3_TTS_URL:-http://localhost:8881/v1/audio/speech}"
        QWEN3_TTS_VOICE="${QWEN3_TTS_VOICE:-Jarvis}"
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
        TEMP_AUDIO="/tmp/jarvis-status-local-$$.${QWEN3_TTS_FORMAT}"
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
        
    else
        # ============================================================================
        # KOKORO TTS (default)
        # ============================================================================
        KOKORO_URL="${KOKORO_TTS_URL:-}"
        KOKORO_VOICE="${KOKORO_TTS_VOICE:-af_nicole}"
        KOKORO_SPEED="${KOKORO_TTS_SPEED:-1.0}"
        
        if [ -z "$KOKORO_URL" ]; then
            echo "❌ KOKORO_TTS_URL not set" >&2
            exit 1
        fi
        
        # Build Kokoro JSON
        TTS_JSON=$(jq -n \
          --arg voice "$KOKORO_VOICE" \
          --arg input "$SANITIZED" \
          --arg speed "$KOKORO_SPEED" \
          '{voice:$voice, input:$input, speed:$speed}')

        # Generate TTS audio via Kokoro
        if ! curl -sS -X POST "$KOKORO_URL" \
            -H "Content-Type: application/json" \
            -d "$TTS_JSON" \
            | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null; then
            echo "⚠️ Local TTS generation failed" >&2
            exit 1
        fi
    fi

    # Check if audio was generated
    if [ ! -f "$OUTFILE" ] || [ ! -s "$OUTFILE" ]; then
        echo "⚠️ TTS output empty" >&2
        exit 1
    fi

    # Add silence padding at the beginning (helps Bluetooth/wireless speakers wake up)
    if command -v sox &>/dev/null && [ "$SILENCE_PAD_MS" -gt 0 ]; then
        PADDED_FILE="/tmp/jarvis-status-local-padded-$$.wav"
        # Convert ms to seconds for sox (e.g., 250ms = 0.25s)
        SILENCE_SECS=$(echo "scale=3; $SILENCE_PAD_MS / 1000" | bc)
        sox -n -r "$RATE" -c 2 -b 16 "/tmp/jarvis-silence-local-$$.wav" trim 0.0 "$SILENCE_SECS" 2>/dev/null
        sox "/tmp/jarvis-silence-local-$$.wav" "$OUTFILE" "$PADDED_FILE" 2>/dev/null
        mv "$PADDED_FILE" "$OUTFILE"
        rm -f "/tmp/jarvis-silence-local-$$.wav" 2>/dev/null
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
