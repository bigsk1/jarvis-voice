#!/bin/bash
# Jarvis Voice Assistant - Question Handler with Orchestrator (Cloud)
# Records audio, transcribes, routes through orchestrator, and speaks response
set -euo pipefail

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load config
source "$PROJECT_ROOT/lib/config_loader.sh"
load_config "cloud"

# Script paths
SAY_SCRIPT="$PROJECT_ROOT/bin/say.sh"
ORCHESTRATOR="$PROJECT_ROOT/orchestrator/orchestrator_v2.py"

# Audio paths
TIMESTAMP=$(date +"%Y-%m-%d-%H%M%S")
MIC_WAV="$AUDIO_DIR/mic/mic-${TIMESTAMP}.wav"
TRANSCRIPT_FILE="$AUDIO_DIR/logs/qa-${TIMESTAMP}.txt"

# Create directories
mkdir -p "$AUDIO_DIR/mic"
mkdir -p "$AUDIO_DIR/recordings"
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
    
    # Check file size
    BYTES=$(stat -c%s "$MIC_WAV" || echo 0)
    if [ "$BYTES" -lt 20000 ]; then
        echo "⚠️ Very short recording ($BYTES bytes). Try speaking louder/longer." >&2
        exit 1
    fi
    
    # Transcribe using OpenAI API
    echo "📝 Transcribing…"
    TRANSCRIPT=$(
        curl -sS https://api.openai.com/v1/audio/transcriptions \
            -H "Authorization: Bearer $OPENAI_API_KEY" \
            -H "Content-Type: multipart/form-data" \
            -F "file=@$MIC_WAV" \
            -F "model=$STT_MODEL" \
        | jq -r '.text // empty'
    )
    
    if [ -z "$TRANSCRIPT" ]; then
        echo "❌ Transcription failed or empty." >&2
        exit 1
    fi
    
    echo "🙋 You asked: $TRANSCRIPT"
fi

# Save transcript
echo "$TRANSCRIPT" > "$TRANSCRIPT_FILE"

# Process through orchestrator
echo "🧠 Processing with orchestrator..."
ORCH_RESULT=$(python3 "$ORCHESTRATOR" cloud "$TRANSCRIPT" --json 2>/dev/null)

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
"$SAY_SCRIPT" "$SPEECH"

echo "✅ Saved:"
echo "   Your question text : $TRANSCRIPT_FILE"
echo "   Your question audio: $MIC_WAV"

# Exit with success if orchestrator succeeded
if [ "$OK" == "true" ]; then
    exit 0
else
    exit 1
fi

