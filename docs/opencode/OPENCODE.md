# OpenCode Integration

![opencode-info-graph](../images/opencode-info-graph.jpeg)


To install OpenCode Server, follow the instructions on the OpenCode Github Repo https://opencode.ai/docs/

```bash
curl -fsSL https://opencode.ai/install | bash
```


## Quick Start

```bash
# Check OpenCode is running
systemctl status opencode-jarvis.service

# Use via Jarvis
./jarvis
# Say: "Hey Jarvis, use OpenCode to create a Python hello world script"

# View logs
./bin/opencode-logs --verbose

# Test integration
./tests/integration/test-opencode-integration.sh
```

---

## What is OpenCode?

OpenCode is an **autonomous coding agent** that Jarvis can call for complex tasks:

- **Writing code** - Full applications, scripts, utilities
- **Debugging** - Analyze and fix code issues
- **Building projects** - Websites, APIs, tools
- **File operations** - Create, modify, organize files
- **Git operations** - Commits, branches, deployments
- **Analysis** - Code review, architecture suggestions

**Flow:**
```
YOU (voice): "Hey Jarvis, build a Flask API"
    ↓
JARVIS: Routes to OpenCode tool
    ↓
OPENCODE: Creates project structure, writes code, tests
    ↓
JARVIS: "I've created a Flask API in your workspace with 5 endpoints..."
```

## Current Runtime Behavior

OpenCode is working again and the current integration is intentionally simple and reliable:

- Jarvis routes one build/coding request to the `opencode` tool
- Jarvis sends a single long-running request to the OpenCode HTTP API
- Jarvis waits for the final result (up to 6 minutes timeout)
- Jarvis shows generic "building" status updates while waiting
- Jarvis summarizes the returned build result for voice/web response

Important details:

- **Not fire-and-forget**: Jarvis waits for the OpenCode result before answering
- **Not true live progress yet**: current status updates are Jarvis-side filler, not streamed OpenCode step events
- **Session/log checks are fallback-only**: `check_opencode_sessions` is useful when a run stalls, returns no usable result, or the user explicitly asks for session status/logs
- **Successful builds should answer from OpenCode directly**: Jarvis should not replace a good build summary with a thin session-status recap

Example successful lifecycle in `logs/opencode/opencode-YYYY-MM-DD.jsonl`:

- `session_start`
- `message_sent` for `system`
- `message_sent` for `context`
- `message_sent` for `task`
- `message_received`
- `session_complete`

---

## Setup

### 1. OpenCode Server (Systemd Service)

**Service file**: `systemd/opencode-jarvis.service`

```bash
# Install service
./bin/install-opencode-service.sh

# Manage service
sudo systemctl status opencode-jarvis.service
sudo systemctl restart opencode-jarvis.service
sudo systemctl stop opencode-jarvis.service

# View logs
journalctl -u opencode-jarvis.service -f
```

**Configuration:**
- Port: `4096`
- Host: `0.0.0.0` (accessible from local network)
- Config: `~/.config/opencode/opencode.json`
- API Keys: `~/.config/opencode/jarvis-env.env`

### 2. Workspace Structure

```
/home/boss/
├── jarvis-voice/           ← READ-ONLY for OpenCode
│   └── ...Jarvis code...
│
└── jarvis-workspace/       ← OpenCode writes here
    ├── projects/
    │   ├── websites/
    │   ├── scripts/
    │   └── experiments/
    ├── temp/               ← Auto-cleanup
    └── deployments/        ← Production-ready builds
```

**Security:**
- OpenCode can only write to `/home/boss/jarvis-workspace`
- `/home/boss/jarvis-voice` is read-only
- Defined in `~/.config/opencode/opencode.json`:
  ```json
  "workspace": {
    "root": "/home/boss/jarvis-workspace",
    "allowedPaths": ["/home/boss/jarvis-workspace"],
    "readOnlyPaths": ["/home/boss/jarvis-voice"]
  }
  ```

### 3. Model Configuration

Jarvis now prefers dedicated OpenCode config values first:

- `OPENCODE_PROVIDER`
- `OPENCODE_MODEL`

If those are set in Jarvis config, the OpenCode tool uses them directly.
If they are not set, it falls back to mode-specific defaults.

**Cloud mode**:
- Provider/model come from `OPENCODE_PROVIDER` and `OPENCODE_MODEL`
- Example current setup: OpenAI + `gpt-5.3-codex`

**Local mode** (when using `jarvis-local`, fallback behavior):
- Provider: Ollama
- Model: `qwen3-vl` (8B, best for tool calling on 16GB GPU)
- Server: Remote at `http://localhost:11434`

Configured across:

- Jarvis mode config (`config/cloud.env`, `config/local.env`)
- OpenCode config: `~/.config/opencode/opencode.json`

### 4. Memory Context

OpenCode no longer gets Jarvis memory by default for ordinary build tasks.

Current behavior:

- Default: task/workspace context only
- Optional: set `OPENCODE_INCLUDE_MEMORY=true` to inject relevant Jarvis memory

Why:

- Build tasks usually do not need broad Jarvis memory context
- Avoids polluting coding tasks with unrelated memory blobs
- Keeps prompts smaller and more deterministic

---

## Usage

### Via Voice

```bash
./jarvis  # or ./jarvis-local

# Say:
"Hey Jarvis, use OpenCode to..."
  - "create a Python script that fetches weather data"
  - "build a simple website with a contact form"
  - "analyze the code in my project folder"
  - "fix the bug in my Flask app"
```

### Via Command Line

```bash
# Direct test
./orchestrator/orchestrator_v2.py cloud "Use OpenCode to create a hello world in Python"

# Through tool
python3 skills/opencode.py '{"task": "Create test.py with hello world"}'
```

---

## Logging & Debugging

### Log Files

1. **`logs/opencode/opencode-YYYY-MM-DD.jsonl`** - Detailed Jarvis ↔ OpenCode conversation
2. **`logs/tools/tool-calls-YYYY-MM-DD.jsonl`** - All tool executions (including OpenCode)

### View Logs

```bash
# Recent activity
./bin/opencode-logs

# Detailed with responses
./bin/opencode-logs --verbose

# Specific session
LATEST=$(grep '"event": "session_start"' logs/opencode/*.jsonl | tail -1 | jq -r '.session_id')
./bin/opencode-session "$LATEST"

# Just OpenCode's responses
grep '"event": "message_received"' logs/opencode/*.jsonl | jq -r '.response_preview'
```

### Read a Specific Session

```bash
SID="ses_example"
grep "$SID" logs/opencode/opencode-$(date +%F).jsonl | jq .
```

### Open a Session in the OpenCode UI

If the OpenCode web UI is reachable on your network, you can often jump straight to a session by ID.

Current working pattern:

```text
http://192.168.70.228:4096/Lw/session/<session_id>
```

Example:

```text
http://192.168.70.228:4096/Lw/session/ses_2a79a23d0ffe6BZWR6GBT7gamY
```

Notes:

- Replace the host if your OpenCode server is running elsewhere
- The current UI route uses the raw `session_id`
- This is handy when the OpenCode UI no longer shows the full session list by default
- If the UI changes again, `./bin/opencode-session <session_id>` is still the reliable fallback

### What to Look For

**Good response** (`message_received`):
```json
{
  "response_preview": "I've created hello.py in /home/boss/jarvis-workspace/projects/scripts/ with...",
  "response_length": 450,
  "duration_ms": 3500
}
```

**Problem indicators:**
- `response_length: 0` - OpenCode didn't respond
- `duration_ms` near the 360000ms timeout with no useful response - likely stalled or timed out
- `ok: false` in tool-calls log - Task failed

**Normal timing reality:**
- Small builds often take 30-90 seconds
- Larger builds can take 2-5 minutes
- Long duration alone is not a failure if `message_received` and `session_complete` show success

### Status Update Reality Today

During a long build, Jarvis currently speaks/shows generic progress phrases such as:

- "OpenCode is working on your request"
- "Still building"
- "Almost there"

These are **not** live step-by-step updates from OpenCode itself.
They are background Jarvis status messages while waiting on one blocking OpenCode API call.

That means:

- you will not currently hear "creating index.html now" unless OpenCode includes that in the final result
- permission prompts or internal OpenCode pauses are not streamed back as structured live events
- if real progress visibility is needed, logs or OpenCode UI are still the best source

### Troubleshooting

```bash
# 1. Server running?
systemctl status opencode-jarvis.service

# 2. Can reach API?
curl http://localhost:4096/health

# 3. Recent errors?
./bin/opencode-logs | grep "❌"

# 4. Check tool execution
grep '"tool": "opencode"' logs/tools/*.jsonl | tail -1 | jq .

# 5. Run integration test
./tests/integration/test-opencode-integration.sh
```

**Common fixes:**
```bash
# Restart server
sudo systemctl restart opencode-jarvis.service

# Update API keys
./bin/update-opencode-service.sh

# Check config is valid
curl http://localhost:4096/config
```

---

## System Prompt

OpenCode receives this system prompt with every task:

**Key points:**
- Identity: "You are OpenCode" (not "Claude Code")
- Audience: Responding to Jarvis (powerful LLM), not directly to user
- Style: Technical and detailed - Jarvis will translate to casual speech
- Boundaries: Read-only for `/home/boss/jarvis-voice`, writable to `/home/boss/jarvis-workspace`
- Focus: Skip lengthy intros, get straight to work

**Full prompt** in `lib/opencode_client.py` lines 150-185

---

## Implementation Status

### ✅ Phase 1 Complete
- [x] OpenCode server setup (systemd service)
- [x] Python client wrapper (`lib/opencode_client.py`)
- [x] Jarvis tool integration (`skills/opencode.py`)
- [x] Workspace structure (`~/jarvis-workspace`)
- [x] Voice command routing
- [x] Basic testing

### ✅ Additional Features (Added)
- [x] Systemd service for auto-start
- [x] Detailed logging system
- [x] Session conversation viewer
- [x] Model selection (cloud/local)
- [x] Integration tests
- [x] OpenCode identifies as "OpenCode" (not "Claude Code")
- [x] Workspace isolation configured
- [x] Fallback-only session verification (`check_opencode_sessions`)
- [x] Build-result-first response path (successful OpenCode output should win over session status text)
- [x] `agent_mode` forwarding (`build` / `plan`)
- [x] Stop/cancel handling improved for long-running local tool execution

### 🚧 Phase 2 In Progress
- [x] **Workspace enforcement** - Verify OpenCode respects boundaries (DONE Confirmed works)
- [ ] **Supervised agent loop** - OpenCode asks Jarvis when blocked, Jarvis answers or escalates to user
- [ ] **Live progress streaming** - Surface real build steps/permission states instead of generic filler updates
- [ ] **Memory strategy** - Decide when Jarvis should inject memory vs keep OpenCode task-only
- [ ] **Structured artifact reporting** - Return created files, run commands, and test status in a more machine-usable way
- [ ] **Resume existing OpenCode sessions from follow-up requests** - Use `jarvis_session`, optional `web_conversation_id`, and prior `session_id` context so requests like "add keyboard support" continue the existing OpenCode project/session instead of starting fresh when appropriate

## Longer-Term Architecture Direction

The intended architecture is still:

```text
User
  -> Jarvis (frontier/top-level orchestrator)
    -> OpenCode (specialized lower-level coding agent)
```

Desired future behavior:

- Jarvis supervises OpenCode like an operator, not just a relay
- If OpenCode has a question, Jarvis answers when possible
- If OpenCode gets off-task, Jarvis corrects it
- If OpenCode hits a true decision point, Jarvis escalates to the user
- OpenCode remains isolated in `~/jarvis-workspace` so it can build autonomous artifacts without touching the main Jarvis repo
- Jarvis can detect when a new user request is really a continuation of the last OpenCode build and resume that same session/project deliberately

That supervision loop is not fully implemented yet, but the current workspace-isolated model is the foundation for it.
- [x] **Context injection** - Pass user preferences, credentials to OpenCode (We already have .env in /home/boss/.config/opencode/jarvis-env.env)
- [ ] **Session persistence** - Resume long-running tasks - with Jarvis to opencode, currently 300 sec timeout on jarvis? waiting for opencode, but jarvis can check opencode logs without triggering another opencode tool call
- [x] **Improved condensation** - Better voice response formatting - works fine currently

---

## Files

### Core Implementation
- `lib/opencode_client.py` (309 lines) - HTTP API client
- `lib/opencode_logger.py` (156 lines) - Logging system
- `skills/opencode.py` (120 lines) - Jarvis tool
- `skills/opencode.tool.json` - Tool schema

### Scripts
- `setup_opencode_workspace.sh` - Create workspace structure
- `bin/setup-opencode-config.sh` - Generate OpenCode config
- `bin/install-opencode-service.sh` - Install systemd service
- `bin/update-opencode-service.sh` - Update environment & restart
- `bin/create-opencode-env.sh` - Create systemd env file
- `bin/opencode-logs` - Log viewer
- `bin/opencode-session` - Session conversation viewer

### Configuration
- `systemd/opencode-jarvis.service` - Systemd unit file
- `~/.config/opencode/opencode.json` - OpenCode configuration
- `~/.config/opencode/jarvis-env.env` - API keys for systemd
- `config/cloud.env` - Jarvis cloud mode config (includes `OPENCODE_ENABLED=true`)
- `config/local.env` - Jarvis local mode config

### Tests
- `tests/integration/test-opencode-integration.sh` - Full integration test

---

## Configuration Reference

### Environment Variables (`.env` files)

**`config/cloud.env`:**
```bash
OPENCODE_ENABLED=true
OPENCODE_BASE_URL=http://localhost:4096
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-proj-...
```

**`config/local.env`:**
```bash
OPENCODE_ENABLED=true
OPENCODE_BASE_URL=http://localhost:4096
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-vl
```

### OpenCode Config (`~/.config/opencode/opencode.json`)

**Key sections:**
- `provider`: Model providers (Anthropic, OpenAI, Ollama)
- `permission`: Requires user approval for edits and bash commands
- `workspace`: Enforces file system boundaries
- `disabled_providers`: Providers to skip

---

## Performance & Costs

**Typical task durations:**
- Simple greeting: ~3-5 seconds
- Code file creation: ~5-10 seconds
- Full project scaffold: ~15-30 seconds
- Complex analysis: ~20-45 seconds

**Model costs** (approximate):
- Claude Sonnet 4: $3 per million input tokens, $15 per million output
- GPT-5: $2.50/$10 per million tokens
- Ollama (local): Free, but slower

**Cache optimization:**
- OpenCode caches system prompts
- Reduces costs by 90% for repeated calls

---

## Known Limitations

1. **Manual server management** - Must start OpenCode server (systemd handles this)
2. **Permission prompts** - OpenCode asks to confirm file edits and bash commands (by design)
3. **No streaming** - Jarvis waits for complete response before speaking
4. **Session cleanup** - OpenCode may clear session messages after completion (but we log everything)
5. **Workspace enforcement** - Config set, needs testing to verify it works

---

## Related Documentation

- **`MEMORY_SYSTEM.md`** - Jarvis memory database
- **`TESTING.md`** - Testing guide
- **`docs/README.md`** - Documentation index

---

## Quick Reference Commands

```bash
# Service management
sudo systemctl {status|start|stop|restart} opencode-jarvis.service
journalctl -u opencode-jarvis.service -f

# Configuration
cat ~/.config/opencode/opencode.json
./bin/update-opencode-service.sh

# Logging
./bin/opencode-logs --verbose
./bin/opencode-session <session_id>

# Testing
./tests/integration/test-opencode-integration.sh
curl http://localhost:4096/health

# Workspace
ls -la ~/jarvis-workspace/
./setup_opencode_workspace.sh

# Update opencode
opencode upgrade
```

---
