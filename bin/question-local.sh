#!/bin/bash
# Load configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/config_loader.sh"
load_config "local"
TTS_NORMALIZE="$SCRIPT_DIR/tts-normalize.py"

# Ask locally via Ollama; sanitize; TTS via configured local provider; save artifacts
set -euo pipefail

QUESTION="${*:-}"
if [ -z "$QUESTION" ]; then
  echo "Usage: $0 <your question>"
  exit 1
fi

declare -a OLLAMA_URLS=()

build_ollama_urls() {
  local raw="${OLLAMA_BASE_URL:-http://localhost:11434},http://localhost:11434"
  local part normalized
  local -A seen=()

  IFS=',' read -r -a parts <<< "$raw"
  for part in "${parts[@]}"; do
    normalized="$(echo "$part" | xargs)"
    normalized="${normalized%/}"
    [ -z "$normalized" ] && continue
    [ -n "${seen[$normalized]:-}" ] && continue
    seen["$normalized"]=1
    OLLAMA_URLS+=("$normalized")
  done
}

ollama_post() {
  local path="$1"
  local payload="$2"
  local url
  local response_with_code
  local http_code
  local response_body

  for url in "${OLLAMA_URLS[@]}"; do
    response_with_code=$(curl --connect-timeout 2 --max-time 90 -sS \
      -w $'\n%{http_code}' "$url$path" \
      -H "Content-Type: application/json" \
      -d "$payload" 2>/dev/null) || continue

    http_code="${response_with_code##*$'\n'}"
    response_body="${response_with_code%$'\n'*}"

    case "$http_code" in
      500|502|503|504)
        continue
        ;;
    esac

    printf "%s" "$response_body"
    return 0
  done

  return 1
}

build_ollama_urls


OUTDIR="${AUDIO_DIR}"
mkdir -p "$OUTDIR/tts" "$OUTDIR/logs"
STAMP="$(date +%F-%H%M%S)"
TXT_Q="$OUTDIR/logs/qa-local-$STAMP.question.txt"
TXT_A="$OUTDIR/logs/qa-local-$STAMP.answer.txt"
WAV_A="$OUTDIR/tts/qa-local-$STAMP.wav"

echo "$QUESTION" > "$TXT_Q"

# --- Style/control: encourage short, ASCII-safe outputs
SYSTEM_PROMPT="You are a role playing AI assistant called Jarvis. Reply in plain ASCII, no emoji, no markdown, no bullet points."

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
ANSWER=$(ollama_post "/v1/chat/completions" "$REQ" \
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
  ANSWER=$(ollama_post "/api/generate" "$REQ_NATIVE" \
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

SANITIZED=$(python3 "$TTS_NORMALIZE" "$SANITIZED")
if [ -z "$SANITIZED" ]; then
  SANITIZED="Done. I shared the details in chat."
fi

# --- If still too long, summarize locally to keep TTS snappy
MAX_CHARS=400
if [ "${#SANITIZED}" -gt "$MAX_CHARS" ]; then
  SUM_PROMPT="Summarize the following answer in plain ASCII, no emoji, no markdown, into <= 2 short sentences (<= 45 words total). Text:
<<<
$SANITIZED
>>>"
  REQ_SUM=$(jq -n --arg model "$OLLAMA_MODEL" --arg prompt "$SUM_PROMPT" '
    { model: $model, prompt: $prompt, stream: false, options: { num_predict: 150 } }')
  SHORT=$(ollama_post "/api/generate" "$REQ_SUM" | jq -r '.response // empty')
  if [ -n "$SHORT" ]; then
    SANITIZED=$(printf "%s" "$SHORT" \
      | tr -d '\000' | tr '\r' '\n' | sed 's/[[:cntrl:]]//g' | sed 's/[[:space:]]\+/ /g' | sed 's/^ *//;s/ *$//')
    # SANITIZED=$(printf "%s" "$SANITIZED" | iconv -c -f utf-8 -t ascii//TRANSLIT)
    SANITIZED=$(python3 "$TTS_NORMALIZE" "$SANITIZED")
  fi
fi

echo "$SANITIZED" | tee "$TXT_A"

# --- TTS via selected local provider
TTS_PROVIDER="${TTS_PROVIDER:-kokoro}"

if [ "$TTS_PROVIDER" = "qwen3-tts" ]; then
  QWEN3_TTS_URL="${QWEN3_TTS_URL:-http://localhost:8881/v1/audio/speech}"
  QWEN3_TTS_VOICE="${QWEN3_TTS_VOICE:-Jarvis}"
  QWEN3_TTS_FORMAT="${QWEN3_TTS_FORMAT:-mp3}"
  QWEN3_TTS_SPEED="${QWEN3_TTS_SPEED:-1.0}"

  TTS_JSON=$(jq -n \
    --arg model "tts-1" \
    --arg voice "$QWEN3_TTS_VOICE" \
    --arg input "$SANITIZED" \
    --arg format "$QWEN3_TTS_FORMAT" \
    --arg speed "$QWEN3_TTS_SPEED" \
    '{model:$model, voice:$voice, input:$input, response_format:$format, speed:($speed|tonumber)}')

  TEMP_AUDIO="/tmp/jarvis-question-local-$$.${QWEN3_TTS_FORMAT}"
  HTTP_CODE=$(curl -sS -w "%{http_code}" -o "$TEMP_AUDIO" \
    -X POST "$QWEN3_TTS_URL" \
    -H "Content-Type: application/json" \
    -d "$TTS_JSON")

  if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Qwen3-TTS API error (HTTP $HTTP_CODE)" >&2
    cat "$TEMP_AUDIO" >&2
    rm -f "$TEMP_AUDIO"
    exit 1
  fi

  ffmpeg -hide_banner -loglevel error -i "$TEMP_AUDIO" -ar 48000 -ac 2 -f wav -y "$WAV_A"
  rm -f "$TEMP_AUDIO"
elif [ "$TTS_PROVIDER" = "kokoro" ]; then
  jq -n --arg voice "${KOKORO_TTS_VOICE:-af_nicole}" --arg input "$SANITIZED" --arg speed "${KOKORO_TTS_SPEED:-1.0}" '{voice:$voice, input:$input, speed:$speed}' \
  | curl -sS -X POST "${KOKORO_TTS_URL:?KOKORO_TTS_URL not set in local.env}" \
      -H "Content-Type: application/json" \
      -d @- \
  | ffmpeg -hide_banner -loglevel error -i - -ar 48000 -ac 2 -f wav -y "$WAV_A"
else
  echo "❌ Unsupported local TTS_PROVIDER: $TTS_PROVIDER" >&2
  exit 1
fi

# add ~120ms of lead-in silence to avoid cut-ins
sox "$WAV_A" -t wav "$WAV_A.pad.wav" pad 0.2
mv "$WAV_A.pad.wav" "$WAV_A"

aplay -D "$OUT_DEV" "$WAV_A" || true

echo "✅ Saved:"
echo "   Q: $TXT_Q"
echo "   A: $TXT_A"
echo "   Audio: $WAV_A"
