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

**Cloud mode** (default):
- Provider: Anthropic
- Model: `claude-sonnet-4-20250514`

**Local mode** (when using `jarvis-local`):
- Provider: Ollama
- Model: `qwen3-vl` (8B, best for tool calling on 16GB GPU)
- Server: Remote at `http://192.168.70.226:11434`

Configured in `~/.config/opencode/opencode.json`

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
- `duration_ms > 15000` - Timed out
- `ok: false` in tool-calls log - Task failed

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

### 🚧 Phase 2 In Progress
- [x] **Workspace enforcement** - Verify OpenCode respects boundaries (DONE Confirmed works)
- [ ] **Memory integration** - OpenCode can read/write Jarvis memory (or just have jarvis write it instead, which he can already do if ask to save data)
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
OLLAMA_BASE_URL=http://192.168.70.226:11434
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
```

---

