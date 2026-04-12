# Jarvis Logging System

Complete overview of where every log goes and how to find errors across all services.

**Last Updated:** April 12, 2026

---

## Quick Reference: Find Errors Fast

```bash
# === ALL HTTP errors across ALL services (today) ===
cat logs/api/errors-$(date +%Y-%m-%d).jsonl logs/web-ui/errors-$(date +%Y-%m-%d).jsonl logs/memory-ui/errors-$(date +%Y-%m-%d).jsonl logs/intelligence-ui/errors-$(date +%Y-%m-%d).jsonl logs/canvas-ui/errors-$(date +%Y-%m-%d).jsonl 2>/dev/null | jq -c '{service,status,path,timestamp}'

# === Just 401 auth errors (all services, all time) ===
grep '"status": 401' logs/*/errors-*.jsonl logs/api/errors-*.jsonl 2>/dev/null | jq -c '{service,path,client_ip,timestamp}'

# === Just 500 server errors ===
grep '"status": 500' logs/*/errors-*.jsonl logs/api/errors-*.jsonl 2>/dev/null | jq '.'

# === Tool execution failures (today) ===
grep '"ok": false' logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq '{tool,error,timestamp}'

# === Background daemon errors ===
grep -i "error\|traceback\|exception" logs/follow_up_daemon.log logs/self_healing_daemon.log logs/reminder_scheduler.log

# === LLM API errors (today) ===
grep -i "error" logs/llm-calls-$(date +%Y-%m-%d).jsonl | jq '.'

# === Tmux session output (live, last 1000 lines) ===
tmux capture-pane -t jarvis-web -p -S -1000 | grep -iE "(error|traceback|401|500)"
tmux capture-pane -t jarvis-api -p -S -1000 | grep -iE "(error|traceback|401|500)"
```

---

## Log Directory Structure

```
logs/
├── api/                          # FastAPI server (port 8880)
│   ├── access-YYYY-MM-DD.jsonl   #   All HTTP requests (external only)
│   └── errors-YYYY-MM-DD.jsonl   #   4xx/5xx errors (ALL, including loopback)
│
├── web-ui/                       # Web UI (port 5001) [NEW]
│   └── errors-YYYY-MM-DD.jsonl   #   4xx/5xx errors
│
├── memory-ui/                    # Memory Browser (port 5002) [NEW]
│   └── errors-YYYY-MM-DD.jsonl   #   4xx/5xx errors
│
├── intelligence-ui/              # Intelligence Dashboard (port 5003) [NEW]
│   └── errors-YYYY-MM-DD.jsonl   #   4xx/5xx errors
│
├── canvas-ui/                    # Canvas Viewer (port 8890) [NEW]
│   └── errors-YYYY-MM-DD.jsonl   #   4xx/5xx errors
│
├── auth/                         # Authentication events
│   └── auth-YYYY-MM-DD.jsonl     #   Login attempts, token verification
│
├── tools/                        # Tool execution
│   └── tool-calls-YYYY-MM-DD.jsonl  # Every tool call with args, result, timing
│
├── intelligence/                 # Intelligence layer
│   └── intelligence-YYYY-MM-DD.jsonl  # Learning events, insights
│
├── feedback/                     # User feedback signals
│   └── feedback-YYYY-MM-DD.jsonl
│
├── evolution/                    # Prompt evolution
│   ├── evolution-YYYY-MM-DD.jsonl
│   └── system_prompt_suggestion_*.md
│
├── services/                     # Background daemon structured logs
│   ├── follow_up_daemon-YYYY-MM-DD.jsonl
│   ├── self_healing_daemon-YYYY-MM-DD.jsonl
│   └── reminder_scheduler-YYYY-MM-DD.jsonl
│
├── thinking/                     # LLM reasoning/decision logs
│   └── YYYY-MM-DD_decisions.jsonl
│
├── tool-builder/                 # Auto tool builder logs
│   ├── tool-builder-YYYY-MM-DD.jsonl
│   └── ouroboros-research-YYYY-MM-DD.jsonl
│
├── validate-system-prompt/       # Prompt validation results
│   └── validation-*.md
│
├── llm-calls-YYYY-MM-DD.jsonl    # All LLM API calls (tokens, timing, model)
├── workflows-YYYY-MM-DD.jsonl    # Workflow execution logs
│
├── follow_up_daemon.log          # Daemon stdout/stderr (nohup)
├── self_healing_daemon.log       # Daemon stdout/stderr (nohup)
├── reminder_scheduler.log        # Daemon stdout/stderr (nohup)
└── cleanup.log                   # Log cleanup script output
```

---

## Service-by-Service Breakdown

### 1. FastAPI Server (`jarvis-api`, port 8880)

**Middleware:** `RequestLoggingMiddleware` in `api/server.py`

| Log | File | What's Captured |
|-----|------|-----------------|
| Access | `logs/api/access-YYYY-MM-DD.jsonl` | All external HTTP requests (skips loopback) |
| Errors | `logs/api/errors-YYYY-MM-DD.jsonl` | All 4xx/5xx responses (including loopback) |

**Error log format (JSONL):**
```json
{
  "timestamp": "2026-02-05T12:34:56.789",
  "method": "POST",
  "path": "/api/query/orchestrator",
  "query": null,
  "status": 500,
  "duration_ms": 1234.56,
  "client_ip": "192.168.70.100",
  "request_body": "{\"message\": \"...\"}",
  "error": "Connection refused"
}
```

**Notes:**
- Health checks (`/api/health`, `/api/status`) are skipped in access logs
- Loopback (127.0.0.1) access is skipped in access logs but errors are ALWAYS logged
- Auth middleware (`APIAuthMiddleware`) returns 401/403, which then gets logged by the request logger

---

### 2. Web UI (`jarvis-web`, port 5001)

**Middleware:** `flask_error_logger` (shared library in `lib/flask_error_logger.py`)

| Log | File | What's Captured |
|-----|------|-----------------|
| Errors | `logs/web-ui/errors-YYYY-MM-DD.jsonl` | All 4xx/5xx HTTP responses |

**Error log format (JSONL):**
```json
{
  "timestamp": "2026-02-05T12:34:56.789",
  "service": "web-ui",
  "method": "GET",
  "path": "/api/conversations",
  "query": "",
  "status": 401,
  "duration_ms": 2.15,
  "client_ip": "192.168.70.100",
  "response_body": "{\"ok\": false, \"error\": \"Authentication required\"}"
}
```

**Also outputs to:** tmux session `jarvis-web` (Flask default stderr)

**Notes:**
- The Jarvis Web `/logs` browser is read-only and runs inside the same Flask app on port `5001`
- `/logs` uses the existing Jarvis Web auth/session checks, so protected deployments stay protected there too
- If `/logs` hits a handled or unhandled HTTP error, it lands in the same `logs/web-ui/errors-YYYY-MM-DD.jsonl` stream as the rest of the Web UI

---

### 3. Memory Browser (`jarvis-memory`, port 5002)

**Middleware:** `flask_error_logger`

| Log | File |
|-----|------|
| Errors | `logs/memory-ui/errors-YYYY-MM-DD.jsonl` |

**Also outputs to:** tmux session `jarvis-memory`

---

### 4. Intelligence Dashboard (`jarvis-intelligence`, port 5003)

**Middleware:** `flask_error_logger`

| Log | File |
|-----|------|
| Errors | `logs/intelligence-ui/errors-YYYY-MM-DD.jsonl` |

**Also outputs to:** tmux session `jarvis-intelligence`

---

### 5. Canvas Viewer (`jarvis-canvas`, port 8890)

**Middleware:** `flask_error_logger`

| Log | File |
|-----|------|
| Errors | `logs/canvas-ui/errors-YYYY-MM-DD.jsonl` |

**Also outputs to:** tmux session `jarvis-canvas`

---

### 6. Background Services (`jarvis-services`)

Started via `bin/jarvis-services` using `nohup`, stdout/stderr redirected to log files.

| Service | Stdout/Stderr | Structured Logs |
|---------|---------------|-----------------|
| Follow-up Daemon | `logs/follow_up_daemon.log` | `logs/services/follow_up_daemon-YYYY-MM-DD.jsonl` |
| Self-healing Daemon | `logs/self_healing_daemon.log` | `logs/services/self_healing_daemon-YYYY-MM-DD.jsonl` |
| Reminder Scheduler | `logs/reminder_scheduler.log` | `logs/services/reminder_scheduler-YYYY-MM-DD.jsonl` |

---

### 7. Tool Execution (`orchestrator/executor.py`)

| Log | File | What's Captured |
|-----|------|-----------------|
| Tool calls | `logs/tools/tool-calls-YYYY-MM-DD.jsonl` | Tool name, args, result, duration, success/fail |

**Notes:**
- Tool subprocess stderr is captured but only included in the log entry if the tool fails (JSON parse error)
- MCP server stderr goes to the parent tmux session, not to a file
- Tool subprocess environment: passes `os.environ.copy()` (all env vars)

---

### 8. LLM API Calls

| Log | File | What's Captured |
|-----|------|-----------------|
| LLM calls | `logs/llm-calls-YYYY-MM-DD.jsonl` | Model, tokens (input/output), latency, provider, cost estimate |

---

### 9. Authentication Events

| Log | File | What's Captured |
|-----|------|-----------------|
| Auth | `logs/auth/auth-YYYY-MM-DD.jsonl` | Login attempts, token creation, verification |

---

### 10. OpenCode (systemd)

| Log | Destination |
|-----|-------------|
| stdout/stderr | systemd journal |

```bash
# View OpenCode logs
journalctl -u opencode-jarvis.service --since today
journalctl -u opencode-jarvis.service -f  # Follow live
```

---

## Log Format

All structured logs use **JSONL** (one JSON object per line) with daily rotation:

```
{type}-YYYY-MM-DD.jsonl
```

This makes them easy to:
- `grep` for specific fields
- Pipe to `jq` for filtering/formatting
- Process with standard Unix tools
- Archive or rotate by date

---

## Common Troubleshooting Commands

### Auth Issues
```bash
# Who's getting 401s and where?
grep '"status": 401' logs/*/errors-*.jsonl logs/api/errors-*.jsonl 2>/dev/null | \
  jq -r '[.timestamp, .service // "api", .path, .client_ip] | @tsv' | sort

# Recent login attempts
cat logs/auth/auth-$(date +%Y-%m-%d).jsonl | jq '.'
```

### Server Errors (500s)
```bash
# All 500 errors with tracebacks
grep '"status": 500' logs/*/errors-*.jsonl logs/api/errors-*.jsonl 2>/dev/null | jq '.'

# Count errors by service today
for f in logs/*/errors-$(date +%Y-%m-%d).jsonl logs/api/errors-$(date +%Y-%m-%d).jsonl; do
  [ -f "$f" ] && echo "$(wc -l < "$f") $(dirname "$f" | xargs basename)"
done 2>/dev/null | sort -rn
```

### Tool Failures
```bash
# Failed tool calls today
grep '"ok": false' logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | \
  jq '{tool: .tool_name, error: .error, time: .timestamp}'

# Slowest tool calls
cat logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | \
  jq -r '[.duration_ms, .tool_name] | @tsv' | sort -rn | head -20
```

### LLM Issues
```bash
# LLM errors or high latency
cat logs/llm-calls-$(date +%Y-%m-%d).jsonl | \
  jq 'select(.error != null or .duration_ms > 30000)'
```

### Daemon Health
```bash
# Recent daemon errors
tail -100 logs/follow_up_daemon.log | grep -i "error\|exception"
tail -100 logs/self_healing_daemon.log | grep -i "error\|exception"
tail -100 logs/reminder_scheduler.log | grep -i "error\|exception"
```

### Live Monitoring
```bash
# Watch all error logs in real-time
tail -f logs/*/errors-$(date +%Y-%m-%d).jsonl logs/api/errors-$(date +%Y-%m-%d).jsonl 2>/dev/null

# Watch a specific tmux session
tmux attach -t jarvis-web    # Ctrl+B then D to detach

# Capture tmux output to search
tmux capture-pane -t jarvis-web -p -S -5000 > /tmp/web-output.txt
grep -iE "(error|traceback|500|401)" /tmp/web-output.txt
```

---

## What's NOT Logged to Files

| Source | Where It Goes | How to Access |
|--------|--------------|---------------|
| Flask stdout (print statements) | tmux session buffer | `tmux capture-pane -t {session} -p` |
| MCP server stderr | tmux session buffer | Same as above |
| Tool subprocess stderr (on success) | Discarded | Only captured on failure |
| SocketIO events | tmux session buffer | Attach to `jarvis-web` session |

**Tip:** If you need to debug something that's only in a tmux buffer, capture it before restarting:
```bash
tmux capture-pane -t jarvis-web -p -S - > logs/web-session-dump-$(date +%Y%m%d_%H%M%S).txt
```

---

## Log Rotation & Cleanup

- Structured logs rotate automatically by date (one file per day)
- Daemon `.log` files (nohup) grow indefinitely - restart resets them
- No automatic cleanup is configured

**Manual cleanup:**
```bash
# Remove logs older than 30 days
find logs/ -name "*.jsonl" -mtime +30 -delete
find logs/ -name "*.log" -mtime +30 -delete
```

---

## Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │              tmux sessions               │
                    │  (stdout/stderr for all services)        │
                    └───────┬────────┬────────┬───────────────┘
                            │        │        │
┌───────────────┐  ┌────────┴──┐ ┌───┴────┐ ┌─┴──────────────┐
│  jarvis-api   │  │ jarvis-   │ │ jarvis-│ │ jarvis-memory  │
│  (FastAPI)    │  │ web       │ │ canvas │ │ jarvis-intel   │
│  port 8880    │  │ port 5001 │ │ p:8890 │ │ p:5002, 5003   │
├───────────────┤  ├───────────┤ ├────────┤ ├────────────────┤
│ Middleware:   │  │ Middleware:│ │  flask │ │  flask         │
│ Request       │  │ flask_    │ │  error │ │  error         │
│ Logging       │  │ error_    │ │  logger│ │  logger        │
│ Middleware    │  │ logger    │ │        │ │                │
└───────┬───────┘  └─────┬─────┘ └───┬────┘ └───────┬────────┘
        │                │           │               │
        v                v           v               v
  logs/api/        logs/web-ui/ logs/canvas-ui/ logs/memory-ui/
  ├─ access-*.jsonl  errors-*    errors-*      logs/intelligence-ui/
  └─ errors-*.jsonl                              errors-*

┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐
│ Tool Executor   │  │ LLM Provider │  │ Background      │
│ (subprocess)    │  │ (API calls)  │  │ Daemons (nohup) │
└────────┬────────┘  └──────┬───────┘  └────────┬────────┘
         │                  │                    │
         v                  v                    v
   logs/tools/       logs/llm-calls-*    logs/services/
   tool-calls-*                          logs/*.log
```

---

## Implementation Details

### Shared Flask Error Logger (`lib/flask_error_logger.py`)

One-line setup for any Flask app:

```python
from flask_error_logger import setup_error_logging
setup_error_logging(app, 'my-service')
```

This registers:
- `@app.before_request` — starts a timer
- `@app.after_request` — logs any 4xx/5xx to `logs/{service}/errors-YYYY-MM-DD.jsonl`
- `@app.errorhandler(Exception)` — catches unhandled 500s with traceback

Skips health checks (`/api/health`, `/api/status`) and static files to avoid noise.

### FastAPI Request Logger (`api/server.py`)

More comprehensive — logs ALL requests (access log) plus errors. Uses ASGI middleware pattern. Configured in `api/server.py` as `RequestLoggingMiddleware`.
