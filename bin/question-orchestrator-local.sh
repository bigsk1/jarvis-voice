#!/bin/bash
# Jarvis Voice Assistant - Question Handler with Orchestrator (Local)
# Records audio, transcribes, routes through orchestrator, and speaks response
set -euo pipefail

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load config
source "$PROJECT_ROOT/lib/config_loader.sh"
load_config "local"

# Script paths
STT_SCRIPT="$PROJECT_ROOT/bin/stt_local.py"
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
        silence 1 "$PRE_SIL" "$THRESH" 1 "$POST_SIL" "$THRESH"
    
    # Transcribe with local whisper
    echo "📝 Transcribing…"
    TRANSCRIPT=$(python3 "$STT_SCRIPT" "$MIC_WAV")
    
    if [ -z "$TRANSCRIPT" ]; then
        echo "❌ No speech detected" >&2
        exit 1
    fi
    
    echo "🙋 You asked: $TRANSCRIPT"
fi

# Save transcript
echo "$TRANSCRIPT" > "$TRANSCRIPT_FILE"

# Process through orchestrator
echo "🧠 Processing with orchestrator..."
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
