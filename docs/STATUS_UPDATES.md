# Status Updates

Jarvis status updates provide short progress feedback while tools run. The
feature began as wake-word silence filler and now uses the same status lifecycle
across wake word, CLI, and Web UI.

The design goal is deliberately modest: keep the user oriented without
streaming model thinking, sending a second model the full conversation, or
making tool execution wait for a status phrase.

## Current Behavior

Status generation is outside the tool critical path:

```text
queue status request ───────────────┐
emit tool:start and execute tool    │ concurrently generate short phrase
                                    │
                                    ├─ phrase ready before deadline → use it
                                    └─ deadline reached → static fallback

tool/turn completes → invalidate pending phrase and stop status audio
final response      → final audio receives strict playback priority
```

The shipped env-example timing is:

- `250 ms` debounce before any phrase may be emitted
- `1000 ms` deadline for the optional Status LLM
- `18 seconds` minimum between phrases that were actually emitted

`STATUS_UPDATE_INTERVAL` retains a 20-second internal fallback when the setting
is entirely absent; the maintained cloud/local env templates set it to 18.

Fast tools therefore often show only Web tool cards and produce no spoken
status. A six-tool request producing one or two phrases is normal when the tools
finish quickly. A suppressed phrase does not consume the interval and prevent a
later, slower tool from reporting status.

Only one Status LLM request runs at a time. A provider request that exceeds the
deadline may finish in its daemon thread, but its result is discarded; it does
not delay the tool or start another overlapping Status LLM request.

## Dynamic Phrase and Static Fallback

`STATUS_UPDATES_ENABLED` is the master switch. When enabled:

1. If `STATUS_LLM_ENABLED=true` and its provider is available, Jarvis races a
   short dynamic phrase against `STATUS_LLM_DEADLINE_MS`.
2. If the model fails or misses the deadline, Jarvis uses a phrase from
   `config/status_phrases.json` (or the unhinged phrase file).
3. If the tool or turn completes before the debounce/phrase wins, Jarvis says
   nothing.

Static phrases remain a full operating mode, not merely an error path. Set
`STATUS_LLM_ENABLED=false` for predictable, zero-LLM progress feedback across
all three interfaces.

The dynamic model is asked for a natural 5–8 word update. Personality settings
still control humor, encouragement, sass, and unhinged mode. Generated output is
cleaned and bounded before delivery.

## Small, Sanitized Context

The Status LLM does not receive the full user transcript, internal thinking,
raw tool output, accumulated conversation, or final-answer prompt.

Its snapshot is capped at 500 characters and may contain:

- phase: starting, running, retrying, or wrapping up
- human-readable tool action
- up to five allowlisted argument fields, each length-limited
- turn number and elapsed time
- one bounded, redacted previous-tool outcome during a multi-tool turn

Argument fields such as credentials, headers, cookies, bodies, content, image
data, audio, and base64 are excluded. URLs are reduced to their origin, and
common secret assignments are redacted. This is both a latency budget and a
provider-data boundary.

`_last_context` is cleared on each new orchestrator turn so a later status
request without explicit context cannot reuse a previous tool's snapshot.

## Delivery Surfaces

| Surface | Text delivery | Audio delivery |
|---|---|---|
| Wake word | Existing voice interaction | `bin/say-status.sh` or `bin/say-status-local.sh` |
| CLI | Terminal/orchestrator lifecycle | Same mode-specific status script |
| Web UI | `chat:status` ephemeral message | Browser requests `/api/tts` with `purpose=status` |

Web `tool:start`, `tool:progress`, `tool:complete`, and `tool:error` are a
separate structured event stream. Tool cards may appear before a dynamic phrase
because execution and presentation are intentionally decoupled.

## Final-Audio Priority and Cancellation

Status audio must never hijack the final answer.

- `mark_complete()` invalidates pending dynamic/static phrases.
- Native status TTS runs in a tracked process group; completion or a new task
  terminates generation/playback cleanly.
- Web status TTS uses an `AbortController` and message identity.
- A final response, error, cancellation, or mode change aborts pending Web
  status TTS and stops status playback.
- Status audio is not allowed to interrupt final audio already playing.

The browser may abort its request while the server-side provider call is already
in progress. That audio is not played; if successful, it can still populate the
status cache for a future identical phrase.

## Observability and Cost Auditing

Actual Status LLM provider requests are written to the normal daily
`logs/llm-calls-YYYY-MM-DD.jsonl` file with `prompt_type=status_update`. Entries
include provider/model, duration, correlation metadata, and provider-reported
token/cache/cost fields when available. They remain auxiliary calls and are not
added to the conversation tooltip's model-call or context totals.

The separate `logs/status-llm/status-updates-YYYY-MM-DD.jsonl` lifecycle log
records:

- Status requests, rate-limit/busy skips, Status LLM starts,
  late/superseded discards, and emitted phrases
- a completion snapshot with attempted/completed/in-flight and outcome counts
- Web status-TTS cache hits, provider starts/completions, and failures

A completion snapshot can legitimately show an in-flight call. Its later
completion/discard is appended as another event, so aggregate the event rows or
the `llm-calls` records rather than treating that snapshot as the final provider
bill.

Example monthly summaries (adjust the filename month):

```bash
jq -s '
  [.[] | select(.prompt_type == "status_update")] |
  {calls: length,
   input_tokens: (map(.input_tokens // 0) | add // 0),
   output_tokens: (map(.output_tokens // 0) | add // 0),
   cost_usd: (map(.cost_usd // 0) | add // 0)}
' logs/llm-calls-2026-07-*.jsonl

jq -s '
  group_by(.event) |
  map({event: .[0].event, count: length})
' logs/status-llm/status-updates-2026-07-*.jsonl
```

Web TTS logging can confirm whether an emitted phrase used cached audio or
started a provider call. Native status phrases are represented by
`phrase_emitted`; the native shell cache remains inspectable with
`./bin/status-cache stats`.

## Audio Caching

Status caching is controlled by `STATUS_CACHE_ENABLED` and is independent of
final-answer TTS.

| Surface | Cache location |
|---|---|
| Native cloud | `~/.cache/jarvis/status-tts/` |
| Native local | `~/.cache/jarvis/status-tts-local/` |
| Web cloud/local | `~/.cache/jarvis/status-tts-web/<mode>/` |

Cache keys include exact phrase text plus the effective provider, voice, model,
and relevant voice settings. Repeated static or dynamic phrases can therefore
play without another ElevenLabs/OpenAI/xAI/local TTS generation call.

```bash
./bin/status-cache stats
./bin/status-cache list
./bin/status-cache clear cloud
./bin/status-cache clear local
./bin/status-cache clear all
./bin/status-cache warm cloud   # Native static phrase pool
./bin/status-cache warm local
```

## Configuration

Current examples live in `config/cloud.env.example`,
`config/cloud.openai.env.example`, and `config/local.env.example`.

```bash
STATUS_UPDATES_ENABLED=true
STATUS_UPDATE_INTERVAL=18
STATUS_UPDATE_DEBOUNCE_MS=250
STATUS_CACHE_ENABLED=true
STATUS_LOGGING_ENABLED=true

STATUS_LLM_ENABLED=true
STATUS_LLM_PROVIDER=openai
STATUS_LLM_MODEL=gpt-4o-mini
STATUS_LLM_DEADLINE_MS=1000
STATUS_LLM_MAX_TOKENS=30

STATUS_PHRASE_MODE=normal
STATUS_HUMOR_ENABLED=true
STATUS_ENCOURAGEMENT_ENABLED=true
STATUS_SASS_LEVEL=1
```

Timing guidance:

- Increase the debounce if fast tools still begin unnecessary speech.
- Reduce the deadline if static fallback should win sooner.
- Increase the interval if long tasks feel too chatty.
- Do not increase the deadline to improve phrase quality: it never blocks the
  tool now, but a long deadline makes useful fallback arrive later.

Web Settings → System shows the effective Status LLM, debounce, deadline,
interval, and cache state for the active mode.

## Tool Triggers

The orchestrator currently requests statuses for:

- OpenCode builds, including periodic long-wait updates
- web search, fetch/browser, and weather tools
- first-turn tools without a more specific category
- later multi-tool turns
- recoverable tool errors
- the wrapping-up phase after tools complete

Memory/recall tools are intentionally skipped because they are normally fast.
Debounce, rate limiting, and completion cancellation can suppress any requested
status when speaking would no longer help.

## OpenCode Boundary

OpenCode remains one blocking Jarvis tool call until it returns or times out.
Jarvis can produce a task-aware phrase from the allowlisted OpenCode `task`
argument, but these phrases are not streamed OpenCode step events.

`check_opencode_sessions` can combine the OpenCode API with Jarvis JSONL logs
after a missing result, timeout, or explicit status/log request. It remains
fallback-only after successful builds. A future active-session bridge may expose
useful incremental log context once the OpenCode session ID is available to the
outer status lifecycle; see `FUTURE_ENHANCEMENTS.md`.

## Implementation and Tests

Primary files:

- `lib/status_updater.py` — deadlines, debounce, context, cancellation, delivery
- `lib/status_llm.py` — provider calls and phrase cleanup
- `lib/status_activity_logger.py` — lifecycle/outcome audit log
- `orchestrator/orchestrator_v2.py` — tool phase/context integration
- `jarvis-web/client/js/app.js` — Web TTS cancellation and final-audio priority
- `jarvis-web/server/routes/api.py` — Web status-only TTS cache
- `bin/say-status*.sh` and `bin/status-cache` — native playback/cache management

Focused regression coverage:

```bash
.venv/bin/python -m pytest -q \
  tests/test_status_updater_latency.py \
  tests/test_status_updater_opencode_auth.py \
  tests/test_web_status_tts_cache.py
```

The original 2025 proposal and implementation sketches remain in
`docs/archive/STATUS_UPDATES_DESIGN.md` as design history. They are not an
operational reference.
