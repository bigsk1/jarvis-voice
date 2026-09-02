#!/bin/bash
# Jarvis Voice Assistant - Question Handler with Orchestrator (Local)
# Records audio, transcribes, routes through orchestrator, and speaks response
#
# Examples:
#   ./bin/question-orchestrator-local.sh
#   ./bin/question-orchestrator-local.sh "what's on my calendar today"
#   # no args: listen from mic; with text: skip recording, run full orchestrator
set -euo pipefail

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load config
source "$PROJECT_ROOT/lib/config_loader.sh"
load_config "local"

# Keep wake-word sensitivity separate from question-recording silence detection.
# THRESH remains a compatibility fallback for older private config files.
START_THRESH="${START_THRESH:-${THRESH:-3%}}"
STOP_THRESH="${STOP_THRESH:-${THRESH:-5%}}"
MIC_HIGHPASS_HZ="${MIC_HIGHPASS_HZ:-300}"

# Script paths
STT_SCRIPT="$PROJECT_ROOT/bin/stt.py"
SAY_SCRIPT="$PROJECT_ROOT/bin/say-local.sh"
TTS_NORMALIZE="$PROJECT_ROOT/bin/tts-normalize.py"
ORCHESTRATOR="$PROJECT_ROOT/orchestrator/orchestrator_v2.py"

# Audio paths
TIMESTAMP=$(date +"%Y-%m-%d-%H%M%S")
MIC_WAV="$AUDIO_DIR/mic/mic-${TIMESTAMP}.wav"
TRANSCRIPT_FILE="$AUDIO_DIR/logs/qa-${TIMESTAMP}.txt"

# Create directories
mkdir -p "$AUDIO_DIR/mic"
mkdir -p "$AUDIO_DIR/tts"
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
    # Record user's question
    echo "🎤 Speak your question… (auto-stops after ${POST_SIL}s silence or ${MAX_RECORD_TIME}s max)"
    sox -t alsa "$IN_DEV" \
        -r "$RATE" -c "$CHAN" -b 16 \
        "$MIC_WAV" \
        trim 0 "$MAX_RECORD_TIME" \
        highpass "$MIC_HIGHPASS_HZ" \
        silence 1 "$PRE_SIL" "$START_THRESH" 1 "$POST_SIL" "$STOP_THRESH"
    
    # Transcribe with the configured local-mode STT provider
    echo "📝 Transcribing…"
    if ! TRANSCRIPT=$(python3 "$STT_SCRIPT" --mode local "$MIC_WAV"); then
        echo "❌ Transcription failed." >&2
        exit 1
    fi
    
    if [ -z "$TRANSCRIPT" ]; then
        echo "❌ No speech detected" >&2
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
ORCH_RESULT=$(python3 "$ORCHESTRATOR" local "$TRANSCRIPT" --json 2>/dev/null)

# Extract speech from orchestrator result
SPEECH=$(echo "$ORCH_RESULT" | jq -r '.speech')
OK=$(echo "$ORCH_RESULT" | jq -r '.ok')

if [ -z "$SPEECH" ] || [ "$SPEECH" == "null" ]; then
    echo "❌ Orchestrator returned no speech" >&2
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
