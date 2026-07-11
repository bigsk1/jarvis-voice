#!/bin/bash
# Shared native TTS playback helpers for Jarvis shell TTS scripts.

jarvis_tts_require_audio_file() {
    local audio_file="$1"
    if [ ! -f "$audio_file" ] || [ ! -s "$audio_file" ]; then
        echo "TTS output missing or empty: $audio_file" >&2
        return 1
    fi
}

jarvis_tts_play_audio_once() {
    local audio_file="$1"
    aplay -D "$OUT_DEV" "$audio_file" 2>/dev/null </dev/null
}

jarvis_tts_play_audio_with_retry() {
    local audio_file="$1"
    local attempts="${TTS_PLAYBACK_ATTEMPTS:-2}"
    local retry_delay="${TTS_PLAYBACK_RETRY_DELAY:-1}"
    local attempt

    if ! [[ "$attempts" =~ ^[0-9]+$ ]] || [ "$attempts" -lt 1 ]; then
        attempts=2
    fi

    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if jarvis_tts_play_audio_once "$audio_file"; then
            return 0
        fi
        if [ "$attempt" -lt "$attempts" ]; then
            echo "TTS playback failed; retrying..." >&2
            sleep "$retry_delay"
        fi
    done

    echo "TTS playback failed after $attempts attempt(s)" >&2
    return 1
}

jarvis_tts_play_audio() {
    local audio_file="$1"
    local lock_file="${TTS_PLAYBACK_LOCK_FILE:-/tmp/jarvis-tts-playback.lock}"
    local lock_timeout="${TTS_PLAYBACK_LOCK_TIMEOUT:-30}"

    jarvis_tts_require_audio_file "$audio_file" || return 1

    if command -v flock >/dev/null 2>&1; then
        mkdir -p "$(dirname "$lock_file")" 2>/dev/null || true
        (
            if ! flock -w "$lock_timeout" 9; then
                echo "TTS playback lock busy after ${lock_timeout}s" >&2
                exit 1
            fi
            jarvis_tts_play_audio_with_retry "$audio_file"
        ) 9>"$lock_file"
        return $?
    fi

    jarvis_tts_play_audio_with_retry "$audio_file"
}
