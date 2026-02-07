#!/bin/bash
# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"

# Ask locally via Ollama; sanitize; TTS via Kokoro; save artifacts
set -euo pipefail

QUESTION="${*:-}"
if [ -z "$QUESTION" ]; then
  echo "Usage: $0 <your question>"
  exit 1
fi


OUTDIR="${AUDIO_DIR}"
mkdir -p "$OUTDIR/tts" "$OUTDIR/logs"
STAMP="$(date +%F-%H%M%S)"
TXT_Q="$OUTDIR/logs/qa-local-$STAMP.question.txt"
TXT_A="$OUTDIR/logs/qa-local-$STAMP.answer.txt"
WAV_A="$OUTDIR/tts/qa-local-$STAMP.wav"

echo "$QUESTION" > "$TXT_Q"

# --- Style/control: encourage short, ASCII-safe outputs
SYSTEM_PROMPT="You are a role playing AI assistant called Jarvis. Reply in plain ASCII, no emoji, no markdown, no bullet points." # Keep it concise and rude: at most four short sentences (<= 100 words total)

# --- Try OpenAI-compatible chat endpoint first (some Ollama builds expose this)
REQ=$(jq -n --arg model "$OLLAMA_MODEL" \
            --arg sys "$SYSTEM_PROMPT" \
            --arg user "$QUESTION" '
{
  model: $model,
  messages: [
    {role:"system", content:$sys},
    {role:"user",   content:$user}
  ],
  stream: false
}')
ANSWER=$(curl -sS "$OLLAMA_BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$REQ" \
  | jq -r '.choices[0].message.content // empty' || true)

# --- Fallback to native /api/generate if needed
if [ -z "$ANSWER" ]; then
  FALLBACK_PROMPT="$SYSTEM_PROMPT

User: $QUESTION

Assistant:"
  REQ_NATIVE=$(jq -n --arg model "$OLLAMA_MODEL" --arg prompt "$FALLBACK_PROMPT" '
    {
      model: $model,
      prompt: $prompt,
      stream: false,
      options: { num_predict: 800 }  # cap output
    }')
  ANSWER=$(curl -sS "$OLLAMA_BASE_URL/api/generate" \
    -H "Content-Type: application/json" \
    -d "$REQ_NATIVE" \
    | jq -r '.response // empty' || true)
fi

if [ -z "$ANSWER" ]; then
  echo "❌ No answer from Ollama."
  exit 1
fi

# --- Sanitize for TTS (remove control chars / collapse whitespace / optional ASCII)
SANITIZED=$(printf "%s" "$ANSWER" \
  | tr -d '\000' \
  | tr '\r' '\n' \
  | sed 's/[[:cntrl:]]//g' \
  | sed 's/[[:space:]]\+/ /g' \
  | sed 's/^ *//;s/ *$//')
# Force ASCII only if Kokoro chokes on Unicode:
# SANITIZED=$(printf "%s" "$SANITIZED" | iconv -c -f utf-8 -t ascii//TRANSLIT)

# --- If still too long, summarize locally to keep TTS snappy
MAX_CHARS=400
if [ "${#SANITIZED}" -gt "$MAX_CHARS" ]; then
  SUM_PROMPT="Summarize the following answer in plain ASCII, no emoji, no markdown, into <= 2 short sentences (<= 45 words total). Text:
<<<
$SANITIZED
>>>"
  REQ_SUM=$(jq -n --arg model "$OLLAMA_MODEL" --arg prompt "$SUM_PROMPT" '
    { model: $model, prompt: $prompt, stream: false, options: { num_predict: 150 } }')
  SHORT=$(curl -sS "$OLLAMA_BASE_URL/api/generate" \
    -H "Content-Type: application/json" \
    -d "$REQ_SUM" | jq -r '.response // empty')
  if [ -n "$SHORT" ]; then
    SANITIZED=$(printf "%s" "$SHORT" \
      | tr -d '\000' | tr '\r' '\n' | sed 's/[[:cntrl:]]//g' | sed 's/[[:space:]]\+/ /g' | sed 's/^ *//;s/ *$//')
    # SANITIZED=$(printf "%s" "$SANITIZED" | iconv -c -f utf-8 -t ascii//TRANSLIT)
  fi
fi

echo "$SANITIZED" | tee "$TXT_A"

# --- TTS via Kokoro, with safe JSON packaging
jq -n --arg voice "$TTS_VOICE" --arg input "$SANITIZED" --arg speed "$TTS_SPEED" '{voice:$voice, input:$input, speed:$speed}' \
| curl -sS -X POST "$TTS_URL" \
    -H "Content-Type: application/json" \
    -d @- \
| ffmpeg -hide_banner -loglevel error -i - -ar 48000 -ac 2 -f wav -y "$WAV_A"

# add ~120ms of lead-in silence to avoid cut-ins
sox "$WAV_A" -t wav "$WAV_A.pad.wav" pad 0.2
mv "$WAV_A.pad.wav" "$WAV_A"

aplay -D $OUT_DEV "$WAV_A" || true

echo "✅ Saved:"
echo "   Q: $TXT_Q"
echo "   A: $TXT_A"
echo "   Audio: $WAV_A"
