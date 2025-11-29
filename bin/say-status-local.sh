#!/bin/bash
# Jarvis Voice Assistant - Status Update TTS (Local/Kokoro)
# Lightweight TTS for local mode - reuses existing Kokoro TTS config
#
# Features:
# - Audio caching: Repeated phrases play instantly (no TTS call)
# - Silence padding: Helps speakers wake up before speech
#
# Usage: say-status-local.sh "message" [blocking]
#   blocking: "true" (wait for playback) or "false" (background)

set -euo pipefail

# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"

TEXT="${1:-}"
BLOCKING="${2:-true}"

if [ -z "$TEXT" ]; then
    echo "Usage: $0 <text to speak> [blocking]" >&2
    exit 1
fi

# ============================================================================
# CACHING SYSTEM
# ============================================================================
# Cache key = hash of (text + voice settings) so changes invalidate cache
STATUS_CACHE_ENABLED="${STATUS_CACHE_ENABLED:-true}"
CACHE_DIR="${HOME}/.cache/jarvis/status-tts-local"
SILENCE_PAD_MS="${STATUS_SILENCE_PAD_MS:-250}"

# Create cache dir if caching enabled
if [ "$STATUS_CACHE_ENABLED" = "true" ]; then
    mkdir -p "$CACHE_DIR"
fi

# Generate cache key from text + voice settings
generate_cache_key() {
    local text="$1"
    # Include voice settings in hash so cache invalidates if settings change
    echo -n "${text}|${TTS_VOICE}|${TTS_SPEED}|${SILENCE_PAD_MS}" | md5sum | cut -d' ' -f1
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

    # Build JSON and call Kokoro TTS (same as say-local.sh)
    TTS_JSON=$(jq -n \
      --arg voice "$TTS_VOICE" \
      --arg input "$SANITIZED" \
      --arg speed "$TTS_SPEED" \
      '{voice:$voice, input:$input, speed:$speed}')

    # Generate TTS audio via Kokoro
    if ! curl -sS -X POST "$TTS_URL" \
        -H "Content-Type: application/json" \
        -d "$TTS_JSON" \
        | ffmpeg -hide_banner -loglevel error -i - -ar "$RATE" -ac 2 -f wav -y "$OUTFILE" 2>/dev/null; then
        echo "⚠️ Local TTS generation failed" >&2
        exit 1
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
