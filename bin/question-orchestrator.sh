#!/bin/bash
# Jarvis Voice Assistant - Question Handler with Orchestrator (Cloud)
# Records audio, transcribes, routes through orchestrator, and speaks response
#
# Examples:
#   ./bin/question-orchestrator.sh
#   ./bin/question-orchestrator.sh "turn off the kitchen light"
#   # no args: listen from mic; with text: skip recording, run full orchestrator
set -euo pipefail

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load config
source "$PROJECT_ROOT/lib/config_loader.sh"
load_config "cloud"

# Script paths
SAY_SCRIPT="$PROJECT_ROOT/bin/say.sh"
TTS_NORMALIZE="$PROJECT_ROOT/bin/tts-normalize.py"
ORCHESTRATOR="$PROJECT_ROOT/orchestrator/orchestrator_v2.py"

# Audio paths
TIMESTAMP=$(date +"%Y-%m-%d-%H%M%S")
MIC_WAV="$AUDIO_DIR/mic/mic-${TIMESTAMP}.wav"
TRANSCRIPT_FILE="$AUDIO_DIR/logs/qa-${TIMESTAMP}.txt"

# Create directories
mkdir -p "$AUDIO_DIR/mic"
mkdir -p "$AUDIO_DIR/recordings"
mkdir -p "$AUDIO_DIR/logs"

configure_wake_response_style() {
    local wake_style="${JARVIS_WAKE_RESPONSE_STYLE:-auto}"

    case "${wake_style,,}" in
        auto|casual)
            export JARVIS_OVERRIDE_JARVIS_RESPONSE_STYLE="${wake_style,,}"
            ;;
        *)
            export JARVIS_OVERRIDE_JARVIS_RESPONSE_STYLE="auto"
            ;;
    esac

    if [ -n "${JARVIS_WAKE_QA_WORD_LIMIT:-}" ]; then
        export JARVIS_OVERRIDE_JARVIS_QA_WORD_LIMIT="$JARVIS_WAKE_QA_WORD_LIMIT"
    fi

    if [ -n "${JARVIS_WAKE_MULTI_TURN_WORD_LIMIT:-}" ]; then
        export JARVIS_OVERRIDE_JARVIS_MULTI_TURN_WORD_LIMIT="$JARVIS_WAKE_MULTI_TURN_WORD_LIMIT"
    fi
}

normalize_control_phrase() {
    printf '%s' "$1" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/^[[:space:][:punct:]]+//; s/[[:space:][:punct:]]+$//; s/[[:space:]]+/ /g'
}

is_exit_command() {
    local normalized
    normalized="$(normalize_control_phrase "$1")"
    case "$normalized" in
        exit|quit|bye|goodbye|"stop listening"|"go to sleep"|sleep)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# If transcript provided as argument, skip recording
if [ -n "${1:-}" ]; then
    TRANSCRIPT="$1"
    echo "📝 Using provided transcript: $TRANSCRIPT"
else
    # Record user's question (retry if wake listener still holds the mic)
    echo "🎤 Speak your question… (auto-stops after ${POST_SIL}s silence or ${MAX_RECORD_TIME}s max)"
    SOX_ERR=$(mktemp)
    for attempt in 1 2 3 4 5; do
        if sox -t alsa "$IN_DEV" \
            -r "$RATE" -c "$CHAN" -b 16 \
            "$MIC_WAV" \
            trim 0 "$MAX_RECORD_TIME" \
            silence 1 "$PRE_SIL" "$THRESH" 1 "$POST_SIL" "$THRESH" \
            2> >(tee "$SOX_ERR" >&2); then
            break
        fi
        if grep -qiE 'busy|resource busy' "$SOX_ERR" && [ "$attempt" -lt 5 ]; then
            echo "⏳ Mic busy (attempt ${attempt}/5), waiting for wake listener to release…" >&2
            sleep 0.5
            continue
        fi
        echo "❌ Recording failed:" >&2
        cat "$SOX_ERR" >&2
        rm -f "$SOX_ERR"
        exit 1
    done
    rm -f "$SOX_ERR"
    
    # Check file size
    BYTES=$(stat -c%s "$MIC_WAV" || echo 0)
    if [ "$BYTES" -lt 20000 ]; then
        echo "⚠️ Very short recording ($BYTES bytes). Try speaking louder/longer." >&2
        exit 1
    fi
    
    # Transcribe using the configured cloud-mode STT provider
    echo "📝 Transcribing…"
    if ! TRANSCRIPT=$(python3 "$PROJECT_ROOT/bin/stt.py" --mode cloud "$MIC_WAV"); then
        echo "❌ Transcription failed." >&2
        exit 1
    fi
    
    if [ -z "$TRANSCRIPT" ]; then
        echo "❌ Transcription failed or empty." >&2
        exit 1
    fi
    
    echo "🙋 You asked: $TRANSCRIPT"
fi

if is_exit_command "$TRANSCRIPT"; then
    echo "🛑 Exit command detected. Stopping wake loop."
    "$SAY_SCRIPT" "Okay, stopping wake word listening."
    exit 20
fi

# Save transcript
echo "$TRANSCRIPT" > "$TRANSCRIPT_FILE"

# Process through orchestrator
echo "🧠 Processing with orchestrator..."
configure_wake_response_style
ORCH_ERR_LOG="$AUDIO_DIR/logs/orchestrator-${TIMESTAMP}.stderr"
ORCH_RESULT=$(python3 "$ORCHESTRATOR" cloud "$TRANSCRIPT" --json 2>"$ORCH_ERR_LOG")

if [ -z "$ORCH_RESULT" ] || ! echo "$ORCH_RESULT" | jq -e . >/dev/null 2>&1; then
    echo "❌ Orchestrator returned invalid JSON" >&2
    if [ -s "$ORCH_ERR_LOG" ]; then
        echo "   stderr (last 20 lines):" >&2
        tail -20 "$ORCH_ERR_LOG" >&2
    fi
    exit 1
fi

# Extract speech from orchestrator result
SPEECH=$(echo "$ORCH_RESULT" | jq -r '.speech')
OK=$(echo "$ORCH_RESULT" | jq -r '.ok')

if [ -z "$SPEECH" ] || [ "$SPEECH" == "null" ]; then
    echo "❌ Orchestrator returned no speech" >&2
    if [ -s "$ORCH_ERR_LOG" ]; then
        tail -20 "$ORCH_ERR_LOG" >&2
    fi
    exit 1
fi

echo "🤖 Response: $SPEECH"

# Speak the response
echo "🗣️ Speaking the answer..."
NORMALIZED_SPEECH=$(python3 "$TTS_NORMALIZE" "$SPEECH")
if [ -z "$NORMALIZED_SPEECH" ]; then
    NORMALIZED_SPEECH="Done. I shared the details in chat."
fi
"$SAY_SCRIPT" "$NORMALIZED_SPEECH"

echo "✅ Saved:"
echo "   Your question text : $TRANSCRIPT_FILE"
echo "   Your question audio: $MIC_WAV"

# Exit with success if orchestrator succeeded
if [ "$OK" == "true" ]; then
    exit 0
else
    exit 1
fi
