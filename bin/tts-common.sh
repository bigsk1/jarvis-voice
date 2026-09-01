#!/bin/bash
# Shared native TTS playback helpers for Jarvis shell TTS scripts.

jarvis_tts_http_to_file() {
    local provider_label="$1"
    local output_file="$2"
    local connect_timeout="$3"
    local request_timeout="$4"
    shift 4

    local http_code
    local curl_status
    if http_code=$(curl -sS -w "%{http_code}" -o "$output_file" \
        --connect-timeout "$connect_timeout" \
        --max-time "$request_timeout" \
        "$@"); then
        printf '%s' "$http_code"
        return 0
    else
        curl_status=$?
        echo "⚠️ ${provider_label} request failed (curl exit ${curl_status})" >&2
        rm -f "$output_file"
        return "$curl_status"
    fi
}

jarvis_tts_require_audio_file() {
    local audio_file="$1"
    if [ ! -f "$audio_file" ] || [ ! -s "$audio_file" ]; then
        echo "TTS output missing or empty: $audio_file" >&2
        return 1
    fi
}

jarvis_head_enabled() {
    case "${JARVIS_HEAD_ENABLED:-false}" in
        1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;;
        *) return 1 ;;
    esac
}

jarvis_head_debug_enabled() {
    case "${JARVIS_HEAD_DEBUG:-false}" in
        1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;;
        *) return 1 ;;
    esac
}

jarvis_head_emit_command() {
    "${BASH_SOURCE[0]%/*}/jarvis-head" emit "$@"
}

jarvis_head_emit() {
    jarvis_head_enabled || return 0

    if jarvis_head_debug_enabled; then
        jarvis_head_emit_command "$@" || true
    else
        jarvis_head_emit_command "$@" >/dev/null 2>&1 || true
    fi
    return 0
}

jarvis_tts_play_audio_once_with_head() (
    local audio_file="$1"
    local playback_id=""
    local playback_status
    local started_at
    local stamp

    stamp="$(date +%s%N 2>/dev/null || printf '%s' "$RANDOM")"
    playback_id="tts-${BASHPID:-$$}-${stamp}-${RANDOM}"
    started_at="$(date +%s.%N 2>/dev/null || true)"
    if [ -n "$started_at" ]; then
        # This trap is scoped to the enabled-path subshell. If StatusUpdater
        # cancels the playback process group, EXIT still closes the overlay.
        trap 'if [ -n "${playback_id:-}" ]; then jarvis_head_emit speak_end --playback-id "$playback_id" --ok false; fi' EXIT
        jarvis_head_emit speak \
            --wav "$audio_file" \
            --playback-id "$playback_id" \
            --t0 "$started_at"
    else
        playback_id=""
    fi

    if aplay -D "$OUT_DEV" "$audio_file" 2>/dev/null </dev/null; then
        playback_status=0
    else
        playback_status=$?
    fi

    if [ -n "$playback_id" ]; then
        if [ "$playback_status" -eq 0 ]; then
            jarvis_head_emit speak_end --playback-id "$playback_id" --ok true
        else
            jarvis_head_emit speak_end --playback-id "$playback_id" --ok false
        fi
        playback_id=""
        trap - EXIT
    fi
    exit "$playback_status"
)

jarvis_tts_play_audio_once() {
    local audio_file="$1"
    local playback_status

    # This function runs inside the playback lock when flock is available.
    # Keep the disabled path to a shell case check: no subshell, Python process,
    # date, or socket work. Each enabled retry gets its own id before its aplay.
    if jarvis_head_enabled; then
        jarvis_tts_play_audio_once_with_head "$audio_file"
        return $?
    fi

    if aplay -D "$OUT_DEV" "$audio_file" 2>/dev/null </dev/null; then
        playback_status=0
    else
        playback_status=$?
    fi
    return "$playback_status"
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
