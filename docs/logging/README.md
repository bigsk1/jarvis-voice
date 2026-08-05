# Jarvis Logging System

Complete map of where Jarvis writes logs, how to inspect them, and which files answer which debugging question.

**Last Updated:** May 12, 2026

---

## Fastest Ways To Inspect Logs

### Web UI Log Viewer

Open the read-only log browser inside Jarvis Web:

```text
http://localhost:5001/logs
```

This is the easiest way to inspect dated `.jsonl`, `.log`, and `.md` files under `logs/` without leaving the browser. It runs inside the existing Jarvis Web app on port `5001`, uses the same auth/session checks as chat, and is intentionally read-only.

Useful for:

- Browsing `llm-calls-*`, `tools/tool-calls-*`, `feedback/*`, `opencode/*`, service logs, and error logs
- Folder/file search
- Lazy loading large files
- YAML-style rendering of JSONL rows
- Reading markdown tickets such as `logs/completion-guard/*.md`

Related API endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /logs` | Dedicated viewer page |
| `GET /api/logs/folders` | List folders with supported log files |
| `GET /api/logs/files` | List files in a folder |
| `GET /api/logs/content` | Fetch paged file content |

### Live Server Logs Panel

Jarvis Web chat also has a live Server Logs panel. It tails current LLM, tool, workflow, OpenCode, and feedback activity for quick in-session debugging. Use `/logs` when you need historical files, dated files, search, or full JSON rows.

### Shell Quick Checks

```bash
# LLM calls today
tail -20 logs/llm-calls-$(date +%F).jsonl | jq .

# Tool failures today
jq 'select(.ok == false)' logs/tools/tool-calls-$(date +%F).jsonl

# HTTP errors across Flask/FastAPI services today
cat logs/api/errors-$(date +%F).jsonl logs/*-ui/errors-$(date +%F).jsonl 2>/dev/null | jq .

# Background daemon errors
grep -iE "error|traceback|exception" logs/services/*-$(date +%F).log logs/*.log 2>/dev/null

# Live tmux output, useful for print() traces and uncaptured stderr
tmux capture-pane -t jarvis-web -p -S -1000 | grep -iE "error|traceback|warning"
```

---

## Log Directory Map

```text
logs/
├── llm-calls-YYYY-MM-DD.jsonl          # Router/provider LLM calls, tokens, cost, latency
├── workflows-YYYY-MM-DD.jsonl          # Workflow execution summaries
├── baseline-tokens-{mode}.json         # Baseline token measurement output
├── cleanup.log                         # Cleanup script output
├── watchdog.log                        # Cron watchdog output, if installed
│
├── api/                                # FastAPI server, port 8880
│   ├── access-YYYY-MM-DD.jsonl         # External HTTP access logs
│   └── errors-YYYY-MM-DD.jsonl         # 4xx/5xx errors
│
├── web-ui/                             # Jarvis Web, port 5001
│   └── errors-YYYY-MM-DD.jsonl         # Web UI and /logs browser errors
├── memory-ui/                          # Memory Browser, port 5002
│   └── errors-YYYY-MM-DD.jsonl
├── intelligence-ui/                    # Intelligence Dashboard, port 5003
│   └── errors-YYYY-MM-DD.jsonl
├── docs-ui/                            # Docs UI, port 5004 when running
│   └── errors-YYYY-MM-DD.jsonl
├── canvas-ui/                          # Canvas Viewer
│   └── errors-YYYY-MM-DD.jsonl
│
├── auth/
│   └── auth-YYYY-MM-DD.jsonl           # Login/session/token events
├── tools/
│   └── tool-calls-YYYY-MM-DD.jsonl     # Tool execution args/result/timing
├── tool-rag/
│   └── tool-rag-YYYY-MM-DD.jsonl       # Tool retrieval traces
├── server-side-tools/
│   └── server-tools-YYYY-MM-DD.jsonl   # Provider-native/server-side tool audit rows
│
├── services/
│   ├── follow_up_daemon-YYYY-MM-DD.jsonl
│   ├── follow_up_daemon-YYYY-MM-DD.log
│   ├── reminder_scheduler-YYYY-MM-DD.jsonl
│   ├── reminder_scheduler-YYYY-MM-DD.log
│   ├── scheduled_task_runner-YYYY-MM-DD.jsonl
│   ├── scheduled_task_runner-YYYY-MM-DD.log
│   ├── self_healing_daemon-YYYY-MM-DD.jsonl
│   └── self_healing_daemon-YYYY-MM-DD.log
│
├── intelligence/
│   └── intelligence-YYYY-MM-DD.jsonl    # Reflection, insight, maintenance events
├── feedback/
│   └── feedback-YYYY-MM-DD.jsonl        # Manual/automatic feedback runs
├── completion-guard/
│   └── *.md                             # Optional unresolved completion tickets
├── opencode/
│   └── opencode-YYYY-MM-DD.jsonl        # OpenCode session events
├── thinking/
│   └── YYYY-MM-DD_decisions.jsonl       # Thinking/decision traces when enabled
├── evolution/
│   ├── evolution-YYYY-MM-DD.jsonl
│   └── system_prompt_suggestion_*.md
├── tool-builder/
│   ├── tool-builder-YYYY-MM-DD.jsonl
│   └── ouroboros-research-YYYY-MM-DD.jsonl
├── validate-system-prompt/
│   └── validation-*.md
├── test/
├── burn-test/
└── self-play/
```

Some services also write PID files under `logs/` while running.

---

## LLM Calls

Primary file:

```text
logs/llm-calls-YYYY-MM-DD.jsonl
```

Written by `lib/llm_logger.py` from router/provider calls. These rows are the best source for “which provider/model did Jarvis call, did it choose a tool, how many tokens did it use, did prompt caching hit, and how long did the LLM take?”

### Core Fields

| Field | Meaning |
|-------|---------|
| `timestamp` | Local ISO timestamp when logged |
| `mode` | `cloud` or `local` |
| `provider` | `xai`, `openai`, `anthropic`, `ollama`, etc. |
| `model` | Provider model id used for the call |
| `prompt_type` | Usually `routing`; may be other internal call types |
| `user_query` | Router prompt or compacted current request context |
| `messages_count` | Number of provider messages sent |
| `routing_provenance` | Auto-context, memory injection, Tool RAG, learning, provider route metadata |
| `input_tokens` / `output_tokens` / `total_tokens` | Provider token usage after adapter normalization |
| `cost_usd` | Estimated cost |
| `reasoning_tokens` | Provider-reported reasoning tokens when available |
| `cached_input_tokens` | Generic cache-read count when provider reports it |
| `cached_prompt_text_tokens` | Generic prompt-cache count for providers that report prompt text cache reads |
| `provider_continuation_mode` | Generic continuation mode, such as `text_fallback`, `stored_structural`, `responses_structural` |
| `provider_previous_response_id_present` | Whether a provider continuation id was available |
| `provider_previous_response_id_used` | Whether a provider continuation id was sent |
| `provider_messages_shape` | Counts/roles only; no message content |
| `response.type` | `text`, `tool_call`, or `error` |
| `response.tool_name` | Tool requested by the model, if any |
| `duration_ms` | LLM/provider call latency |
| `success` / `error` | Provider-call outcome |

### Provider-Specific Fields

Provider-specific fields are written only for the active provider. OpenAI rows do not include empty `xai_*` fields, and xAI rows do not include empty `openai_*` fields.

OpenAI Responses fields:

| Field | Meaning |
|-------|---------|
| `openai_api_mode` | `chat` or `responses` mode seen by provider routing |
| `openai_responses_tools_enabled` | Whether Responses tool routing gate was enabled |
| `openai_responses_previous_id_present` / `used` | Responses `previous_response_id` availability/use |
| `openai_responses_continuation_mode` | OpenAI continuation mode |
| `openai_responses_continuation_input_items` | Number of structural input items, such as `function_call_output` |
| `openai_responses_output_items_by_type` | Counts of typed Responses output items, e.g. `function_call` |
| `openai_responses_fallback_reason` | Adapter fallback reason, if any |
| `openai_prompt_cache_key_set` | Whether Jarvis sent a `prompt_cache_key` |
| `openai_cached_input_tokens` | Cache-read tokens from `usage.input_tokens_details.cached_tokens` |
| `openai_cache_read_tokens` | Same cache-read count in cache-cost terminology |
| `openai_cache_hit` | True when cached tokens were reported |
| `openai_server_side_tool_calls` / `tools` | OpenAI hosted tool usage summary |

xAI fields:

| Field | Meaning |
|-------|---------|
| `xai_prompt_text_tokens` | xAI prompt text token count, when reported |
| `xai_cached_prompt_text_tokens` | xAI cached prompt text tokens, when reported |
| `xai_reasoning_effort` | Configured/reported Grok reasoning effort |
| `xai_continuation_mode` | xAI continuation mode |
| `xai_previous_response_id_present` / `used` | xAI stored continuation availability/use |
| `xai_search_calls` / `xai_search_tools` | xAI server-side search/tool usage summary |

### LLM Debug Queries

```bash
# Latest LLM call, compact summary
tail -1 logs/llm-calls-$(date +%F).jsonl | jq '{provider, model, response, input_tokens, output_tokens, duration_ms}'

# OpenAI Responses cache hits
jq 'select(.provider == "openai") | {t:.timestamp, model, cache:.openai_cached_input_tokens, hit:.openai_cache_hit, key:.openai_prompt_cache_key_set}' \
  logs/llm-calls-$(date +%F).jsonl

# xAI cache/search summary
jq 'select(.provider == "xai") | {t:.timestamp, model, cached:.xai_cached_prompt_text_tokens, search_calls:.xai_search_calls, tools:.xai_search_tools}' \
  logs/llm-calls-$(date +%F).jsonl

# Slow provider calls
jq 'select(.duration_ms > 30000) | {t:.timestamp, provider, model, duration_ms, response:.response.type, tool:.response.tool_name}' \
  logs/llm-calls-$(date +%F).jsonl

# Tool calls requested by the LLM
jq 'select(.response.type == "tool_call") | {t:.timestamp, provider, model, tool:.response.tool_name}' \
  logs/llm-calls-$(date +%F).jsonl
```

Notes:

- `openai_prompt_cache_key_set: true` only means Jarvis sent a cache key. A real cache hit requires `openai_cached_input_tokens > 0`.
- Provider continuation ids are not raw logged in normal rows. The booleans and modes are enough for day-to-day debugging.
- LLM logs are provider-call logs, not final user-message logs. A single user request can create multiple LLM rows during multi-tool orchestration.

---

## Tool Execution

Primary file:

```text
logs/tools/tool-calls-YYYY-MM-DD.jsonl
```

Written by `lib/tool_logger.py` / the orchestrator executor. Use it when the model selected a tool and you need exact arguments, result preview, success/failure, or timing.

Common fields:

| Field | Meaning |
|-------|---------|
| `tool_name` | Tool invoked |
| `arguments` | JSON arguments sent to the tool |
| `result` | Tool result, often including `ok`, `speech`, data, refs |
| `duration_ms` | Tool runtime |
| `ok` / `error` | Tool outcome |

Useful commands:

```bash
# Failed tools today
jq 'select(.ok == false)' logs/tools/tool-calls-$(date +%F).jsonl

# Slowest tools today
jq -r '[.duration_ms, .tool_name] | @tsv' logs/tools/tool-calls-$(date +%F).jsonl | sort -rn | head -20

# Exact calls to one tool
jq 'select(.tool_name == "serpapi_amazon_search")' logs/tools/tool-calls-$(date +%F).jsonl
```

Tool subprocess stderr is captured on failures. MCP server stderr usually appears in the parent service/tmux output.

---

## Tool RAG Traces

Primary file:

```text
logs/tool-rag/tool-rag-YYYY-MM-DD.jsonl
```

Enabled by `TOOL_RAG_TRACE_ENABLED=true`. Use this when the wrong tools were available to the router, or when a tool was missing from the shortlist.

Important fields:

- `provider` / `model`
- `transcript`
- `query`
- `signal_source`
- `threshold`
- `ranked_tools`
- `final_tools`
- `ghost_tools`
- `tool_schema_chars`
- `tool_schema_est_tokens`
- `tool_schema_top`

```bash
# Latest Tool RAG decision
tail -1 logs/tool-rag/tool-rag-$(date +%F).jsonl | jq .

# Which tools actually reached the LLM?
tail -1 logs/tool-rag/tool-rag-$(date +%F).jsonl | jq '.final_tools'
```

---

## HTTP And Web Services

### FastAPI Server

Files:

```text
logs/api/access-YYYY-MM-DD.jsonl
logs/api/errors-YYYY-MM-DD.jsonl
```

`logs/api/access-*` captures external HTTP requests and skips noisy local health checks. `logs/api/errors-*` captures 4xx/5xx responses, including loopback errors.

```bash
# API errors today
jq . logs/api/errors-$(date +%F).jsonl

# Slow API requests
jq 'select(.duration_ms > 1000)' logs/api/access-$(date +%F).jsonl
```

### Flask UI Services

Files:

```text
logs/web-ui/errors-YYYY-MM-DD.jsonl
logs/memory-ui/errors-YYYY-MM-DD.jsonl
logs/intelligence-ui/errors-YYYY-MM-DD.jsonl
logs/docs-ui/errors-YYYY-MM-DD.jsonl
logs/canvas-ui/errors-YYYY-MM-DD.jsonl
```

These are written by `lib/flask_error_logger.py`. They capture 4xx/5xx responses and unhandled exceptions from each Flask UI.

```bash
# All UI errors today
cat logs/*-ui/errors-$(date +%F).jsonl 2>/dev/null | jq '{service, status, path, timestamp}'
```

---

## Background Services

Primary folder:

```text
logs/services/
```

Services generally write both structured `.jsonl` and plain `.log` files:

| Service | Structured | Plain text |
|---------|------------|------------|
| Follow-up daemon | `follow_up_daemon-YYYY-MM-DD.jsonl` | `follow_up_daemon-YYYY-MM-DD.log` |
| Reminder scheduler | `reminder_scheduler-YYYY-MM-DD.jsonl` | `reminder_scheduler-YYYY-MM-DD.log` |
| Scheduled task runner | `scheduled_task_runner-YYYY-MM-DD.jsonl` | `scheduled_task_runner-YYYY-MM-DD.log` |
| Self-healing daemon | `self_healing_daemon-YYYY-MM-DD.jsonl` | `self_healing_daemon-YYYY-MM-DD.log` |

There may also be legacy top-level `.log` files such as `logs/follow_up_daemon.log`.

```bash
# Recent structured service errors
jq 'select(.event == "error" or .ok == false)' logs/services/*-$(date +%F).jsonl

# Recent plain-text daemon errors
grep -iE "error|exception|traceback" logs/services/*-$(date +%F).log logs/*.log 2>/dev/null
```

---

## Other Important Logs

| Folder/File | Use |
|-------------|-----|
| `logs/auth/auth-YYYY-MM-DD.jsonl` | Login attempts, token/session events |
| `logs/intelligence/intelligence-YYYY-MM-DD.jsonl` | Reflection, insight updates, maintenance jobs |
| `logs/feedback/feedback-YYYY-MM-DD.jsonl` | Feedback evaluations and user ratings |
| `logs/completion-guard/*.md` | Optional unresolved completion tickets |
| `logs/opencode/opencode-YYYY-MM-DD.jsonl` | OpenCode session lifecycle and messages |
| `logs/thinking/YYYY-MM-DD_decisions.jsonl` | Thinking/decision traces when enabled |
| `logs/evolution/*` | Prompt evolution events and suggestions |
| `logs/tool-builder/*` | Dynamic tool builder and research traces |
| `logs/validate-system-prompt/*` | Prompt validation reports |
| `logs/burn-test/*` | Explicit burn-test harness output |

---

## What Is Not Always In Files

| Source | Where it usually goes | How to inspect |
|--------|------------------------|----------------|
| `print()` output from Flask/WebSocket paths | tmux pane | `tmux capture-pane -t jarvis-web -p -S -1000` |
| MCP server stderr | parent service/tmux pane | capture the relevant pane |
| Successful tool subprocess stderr | usually discarded | only failure stderr is usually logged |
| Socket.IO event stream details | tmux pane and Web UI state | use chat UI + tmux |
| Browser console errors | browser devtools | open devtools on Jarvis Web |

Before restarting a service, capture tmux output if you need it:

```bash
tmux capture-pane -t jarvis-web -p -S - > logs/web-session-dump-$(date +%Y%m%d_%H%M%S).txt
```

---

## Log Rotation And Cleanup

Most structured logs rotate by date. Retention is handled by cleanup scripts/service docs rather than the logger itself. Check disk usage periodically:

```bash
du -sh logs logs/*
```

Manual cleanup example:

```bash
find logs/ -name "*.jsonl" -mtime +60 -delete
find logs/ -name "*.log" -mtime +60 -delete
```

Do not delete active PID files under `logs/` while services are running.

---

## Implementation Pointers

| Area | Code |
|------|------|
| LLM call logs | `lib/llm_logger.py` |
| Tool call logs | `lib/tool_logger.py` |
| Service logs | `lib/service_logger.py` |
| Flask error logs | `lib/flask_error_logger.py` |
| FastAPI request logs | `api/server.py` |
| Web UI `/logs` page | `jarvis-web/server/app.py`, `jarvis-web/server/routes/api.py`, `jarvis-web/client/js/log-viewer.js` |
| Live server log streamer | `jarvis-web/server/services/log_streamer.py` |
| Tool RAG trace writer | `orchestrator/router_v2.py` |
