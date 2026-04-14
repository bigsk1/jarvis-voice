# Jarvis Tool Builder - Autonomous Tool Creation

> **Version:** 2.1  
> **Updated:** January 21, 2026  
> **Purpose**: Automatically create new tools when capability gaps are detected in feedback. Uses existing LLM providers (no external dependencies) with safety checks and full traceability.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [CLI Commands](#cli-commands)
4. [Integration with Evolution](#integration-with-evolution)
5. [Safety Features](#safety-features)
6. [Configuration](#configuration)
7. [Report Cards & Traceability](#report-cards--traceability)
8. [Directory Structure](#directory-structure)
9. [Grafana Monitoring](#grafana-monitoring)

---

## Overview

The Tool Builder automatically creates new tools when:
1. Feedback consistently mentions a missing capability
2. Manual trigger via CLI

### Key Features

- **Uses existing LLM providers** - No external dependencies (works with xAI, Anthropic, OpenAI, Ollama)
- **Local mode compatible** - Same tool builder works for cloud and local
- **Verification** - Syntax, import, and runtime tests before deployment
- **Dependency gating** - New packages require human approval
- **Full traceability** - Report card links to feedback IDs
- **MCP overlap check** - Skips if existing MCP tool does the job
- **Network/Proxy Auto-Fix** - Detects connection errors and auto-injects proxy instructions
- **Inter-tool Calling** - Guides LLM to call other Jarvis tools correctly
- **Stash Integration** - Built-in patterns for artifact storage

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TOOL CREATION FLOW                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Feedback identifies gap                                            │
│  "No tool for X" / "Had to use workaround"                         │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────────┐                                          │
│  │  Tool Builder LLM    │  Uses TOOL_BUILDER_PROVIDER/MODEL        │
│  │  Generates:          │  Falls back to FEEDBACK_PROVIDER         │
│  │  - tool_name.py      │  Falls back to LLM_PROVIDER              │
│  │  - tool_name.json    │                                          │
│  │  - requirements.txt  │ (if any new deps)                        │
│  └──────────┬───────────┘                                          │
│             │                                                       │
│             ▼                                                       │
│  ┌──────────────────────┐                                          │
│  │  Dependency Check    │                                          │
│  │  - Parse imports     │                                          │
│  │  - Check installed   │                                          │
│  └──────────┬───────────┘                                          │
│             │                                                       │
│      ┌──────┴──────┐                                               │
│      │             │                                                │
│      ▼             ▼                                                │
│  [No new deps]  [New deps needed]                                  │
│      │             │                                                │
│      │             ▼                                                │
│      │      ┌──────────────────┐                                   │
│      │      │ QUEUE FOR REVIEW │                                   │
│      │      │ skills/pending/  │                                   │
│      │      └──────────────────┘                                   │
│      │                                                              │
│      ▼                                                              │
│  ┌──────────────────────┐                                          │
│  │  Verification        │                                          │
│  │  1. Syntax check     │                                          │
│  │  2. Import check     │                                          │
│  │  3. Run with test    │ ←── Uses test_input from json            │
│  │     input            │                                          │
│  └──────────┬───────────┘                                          │
│             │                                                       │
│      ┌──────┴──────┐                                               │
│      │             │                                                │
│      ▼             ▼                                                │
│  [PASS]        [FAIL]                                              │
│      │             │                                                │
│      │             ▼                                                │
│      │      ┌──────────────────┐                                   │
│      │      │ Analyze Error    │                                   │
│      │      │ - Network error? │→ Inject proxy fix instructions   │
│      │      │ - Syntax error?  │→ Show exact error                │
│      │      └────────┬─────────┘                                   │
│      │               ▼                                              │
│      │      ┌──────────────────┐                                   │
│      │      │ Back to LLM      │                                   │
│      │      │ "Fix this error" │                                   │
│      │      │ (max 3 retries)  │                                   │
│      │      └──────────────────┘                                   │
│      │                                                              │
│      ▼                                                              │
│  ┌──────────────────────┐                                          │
│  │ Deploy to            │                                          │
│  │ skills/auto-tools/   │                                          │
│  │ + sync_tools.py      │                                          │
│  │ + log success        │                                          │
│  └──────────────────────┘                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## CLI Commands

### Build a Tool

```bash
# Build from a gap description
./bin/build-tool --mode cloud build "Convert between different units"

# Build with feedback context
./bin/build-tool --mode cloud build "Parse RSS feeds" --feedback-ids fb_001,fb_002

# Local mode
./bin/build-tool --mode local build "Check system disk usage"
```

### Manage Pending Tools

Tools that need new packages go to `skills/pending/` for review:

```bash
# List pending tools
./bin/build-tool list-pending

# Approve and install packages
./bin/build-tool approve my_tool --install

# Approve without installing (you install manually)
./bin/build-tool approve my_tool

# Reject (delete) a pending tool
./bin/build-tool reject my_tool
```

### View Tools

```bash
# List auto-generated tools
./bin/build-tool list-auto

# View report card
./bin/build-tool info my_tool
```

### Sync After Creation

```bash
# Sync to enable new tools
./bin/sync_tools.py cloud  # or local
```

---

## Integration with Evolution

The Tool Builder is automatically triggered during evolution checks when capability gaps are detected.

### Automatic Trigger

```bash
# Run evolution with auto tool building
./bin/evolve-prompts --mode cloud auto --deploy

# Evolution Step 5 will:
# 1. Detect capability gaps from feedback
# 2. Auto-build tools for consistent gaps (mentioned 2+ times)
```

### Gap Detection Patterns

The system looks for feedback mentioning:
- "no tool for X"
- "missing capability for X"
- "couldn't find a tool to X"
- "had to use workaround for X"
- "would be useful to have X"
- "needs a tool to X"

### Configuration

```bash
# In config/cloud.env or config/local.env

# Minimum times a gap must be mentioned to trigger tool creation
EVOLUTION_MIN_GAP_COUNT=2
```

---

## Safety Features

### 1. Duplicate Tool Check

Before building, the LLM sees ALL existing tools (local + MCP + auto-tools):

```
EXISTING TOOLS - DO NOT DUPLICATE THESE:
- weather: Get current weather and forecast for any location...
- get_weather: Get current weather conditions for any city worldwide...
- mcp_brave_search_brave_web_search: Web search via Brave...
- mcp_fetch_fetch: HTTP requests...

If similar tool exists → SKIP_DUPLICATE or SKIP_MCP_EXISTS
```

This prevents creating tools that duplicate existing functionality.

### 2. Trivial Tool Filter

The LLM decides if the tool is worth building:

```
If too simple/unnecessary → SKIP_TRIVIAL
```

### 3. Dependency Gating

**Available packages** (no install needed):
- Standard library: `os`, `sys`, `json`, `re`, `datetime`, `subprocess`, `sqlite3`, etc.
- Jarvis lib modules: `config_loader`, `stash_helper`, `memory_db`, `llm_provider`, `http_client`
- Already installed: `requests`, `yfinance`, `flask`, `beautifulsoup4`, `pyyaml`, `psutil`, `numpy`, etc.

**New packages** → Tool goes to `skills/pending/` for human review.

### 4. API Key Awareness

The Tool Builder knows what API keys are available:

```
SYSTEM INFO:
- Python version: 3.11.8
- Available env vars with API keys: ANTHROPIC_API_KEY, XAI_API_KEY, OPENAI_API_KEY...
```

**If tool requires an API key that doesn't exist:**
- Sets `requires_new_api_key: true`
- Specifies `suggested_env_var: "SOME_API_KEY"`
- Tool goes to `skills/pending/` with status `pending_api_key`
- Shows in `list-pending` with 🔑 indicator

This prevents tools from being deployed that would fail at runtime due to missing credentials.

### 5. Verification Pipeline

1. **Syntax check** - AST parse
2. **Import check** - Try importing
3. **Runtime test** - Run with `test_input` from JSON config

### 6. Retry Loop with Smart Error Analysis

If verification fails, the LLM gets 3 attempts with error feedback to fix it.

**Network Error Detection** - If the error contains network indicators:
- "Failed to connect", "Connection refused", "Read timed out"
- "Could not resolve host", "yahoo.com", "curl"

The retry prompt automatically includes detailed proxy fix instructions.

### 7. Robust JSON Parsing (v2.1)

LLMs often generate Python code with **unescaped newlines** in the `python_code` JSON field, causing parse failures like:
```
Failed to parse JSON: Expecting ',' delimiter: line 14 column 12156
```

The Tool Builder now includes `_extract_python_code_field()` which:
1. Finds the `"python_code":` field in the response
2. Extracts raw code content (including unescaped newlines)
3. Properly escapes: `\n`, `\r`, `\t`, `"`, `\\`
4. Rebuilds valid JSON before parsing

**This fixes the common issue where multi-line Python code breaks JSON parsing.**

---

## Network/Proxy Auto-Fix (NEW)

Many networks require proxy for external API access. The Tool Builder now automatically detects network errors and provides fix instructions.

Canonical reference: **[NETWORK_PROXY.md](NETWORK_PROXY.md)** (`LOCAL_PROXY`, optional `LOCAL_PROXY2`, `lib/http_client.py` chain, direct fallback).

### How It Works

```
Attempt 1: Tool generated without proxy
    ↓
Verification fails: "Failed to connect to yahoo.com"
    ↓
_is_network_error() detects: "yahoo.com" in error → True
    ↓
Attempt 2: Prompt includes proxy fix instructions
    ↓
LLM regenerates tool WITH proxy support
    ↓
Verification passes ✅
```

### Proxy Patterns in BUILD_PROMPT

The LLM is taught three patterns for proxy support (see [NETWORK_PROXY.md](NETWORK_PROXY.md) for full chain behavior):

**Option 1 - requests library (first configured proxy URL):**
```python
from config_loader import load_config
from http_client import get_proxy_config
import requests

def setup_proxy():
    # First non-empty of LOCAL_PROXY, then LOCAL_PROXY2 (same as most Jarvis tools)
    return get_proxy_config()

proxies = setup_proxy()
response = requests.get(url, proxies=proxies, timeout=30)
```

**Option 2 - Environment variables (for yfinance, etc.):**  
For a full **primary → secondary → direct** flow with yfinance, copy the logic in `skills/stock_price.py` (`LOCAL_PROXY` then `LOCAL_PROXY2`, then clear env). Minimal single-proxy setup:

```python
def setup_proxy_env():
    proxy = get_config_value('LOCAL_PROXY', '')
    if proxy:
        os.environ['http_proxy'] = proxy
        os.environ['https_proxy'] = proxy
        return True
    return False
```

**Option 3 - Jarvis http_client (full chain + tunnel HTTP errors):**
```python
from http_client import http_request

response = http_request(
    'GET', url,
    use_proxy=True,
    fallback_on_proxy_fail=True
)
```

### Example: stock_price Tool

The `stock_price` tool uses environment variables for yfinance but walks **`LOCAL_PROXY`** and **`LOCAL_PROXY2`** before falling back to direct. See `skills/stock_price.py` and [NETWORK_PROXY.md](NETWORK_PROXY.md).

---

## Configuration

### LLM Provider

The Tool Builder uses providers in this order:

1. `TOOL_BUILDER_PROVIDER` / `TOOL_BUILDER_MODEL` (if set)
2. `FEEDBACK_PROVIDER` / `FEEDBACK_MODEL` (if set)
3. `LLM_PROVIDER` / provider's default model

```bash
# config/cloud.env

# Dedicated tool builder (optional)
TOOL_BUILDER_PROVIDER=xai
TOOL_BUILDER_MODEL=grok-4.1-fast-non-reasoning-latest

# Or use Anthropic
TOOL_BUILDER_PROVIDER=anthropic
TOOL_BUILDER_MODEL=claude-sonnet-4-5-20250929

# Falls back to FEEDBACK_PROVIDER, then LLM_PROVIDER
```

### Provider Fallback Chain

```
TOOL_BUILDER_PROVIDER → FEEDBACK_PROVIDER → LLM_PROVIDER
```

### Default Models (if not set)

| Provider | Default Model |
|----------|---------------|
| xAI | `grok-4.1-fast-non-reasoning-latest` |
| Anthropic | `claude-sonnet-4-5-20250929` |
| OpenAI | `gpt-4o` |
| Ollama | `qwen3.5:latest` |

---

## Ouroboros Research Pattern 🐍

The Tool Builder can use Jarvis itself to research APIs and documentation before building a tool.

### How It Works

```
Tool Builder needs API info
        ↓
Calls Jarvis Orchestrator (with JARVIS_TOOL_BUILDER_CONTEXT=true)
        ↓
Jarvis uses its tools:
  - mcp_brave_search (web search)
  - mcp_fetch_fetch (get docs)
  - semantic_recall (what exists?)
        ↓
Returns research to Tool Builder
        ↓
Better, more accurate tool created!
```

### Triggers

Research is auto-triggered when the gap description contains:
- API-related: `api`, `endpoint`, `webhook`, `oauth`, `authentication`
- Services: `weather`, `stock`, `crypto`, `translate`, `discord`, `slack`
- Cloud: `aws`, `s3`, `azure`, `gcp`, `database`
- Payments: `stripe`, `paypal`

### CLI Options

```bash
# With research (default for API-related gaps)
./bin/build-tool build "Get stock prices from Yahoo Finance"

# Without research (faster, uses LLM knowledge only)
./bin/build-tool build "Simple text reverser" --no-research
```

### Logs

```bash
# Watch research in real-time
tail -f logs/tool-builder/ouroboros-research-*.jsonl | jq .

# See what Jarvis found
cat logs/tool-builder/ouroboros-research-*.jsonl | jq '{query: .query, tools_used: .tools_used, duration_ms: .duration_ms}'
```

---

## Inter-Tool Calling Pattern

Tools can call other Jarvis tools via subprocess. The BUILD_PROMPT includes detailed guidance:

### Tool Discovery

```python
SKILLS_DIR = os.path.join(os.path.dirname(__file__), '..')
AUTO_TOOLS_DIR = os.path.dirname(__file__)

def find_tool(tool_name):
    for base_dir in [SKILLS_DIR, AUTO_TOOLS_DIR]:
        tool_path = os.path.join(base_dir, f"{tool_name}.py")
        if os.path.exists(tool_path):
            return os.path.abspath(os.path.realpath(tool_path))
    return None
```

### Calling Pattern

```python
def call_tool(tool_name, args=None):
    tool_path = find_tool(tool_name)
    project_root = os.path.join(os.path.dirname(__file__), '..', '..')
    
    result = subprocess.run(
        ["python3", tool_path, json.dumps(args or {})],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=project_root  # CRITICAL: So tools find their lib imports
    )
    
    if result.returncode == 0:
        return json.loads(result.stdout)
    return {"ok": False, "error": result.stderr}
```

### Known Tool Response Structures

The BUILD_PROMPT documents correct data paths for common tools:

| Tool | Data Path | Example |
|------|-----------|---------|
| `stash` (save) | `data.ref` | `result.get('data', {}).get('ref')` |
| `generate_image` | `data.saved.stash_ref` | `result.get('data', {}).get('saved', {}).get('stash_ref')` |
| `crypto_price` | `data.price_usd` | `result.get('data', {}).get('price_usd')` |
| `stock_price` | `data.price_usd` | `result.get('data', {}).get('price_usd')` |
| `system_monitor` | `data.cpu.total_percent` | Nested structure |
| `weather` | `data.temperature` | `result.get('data', {}).get('temperature')` |

### Example: status_recap Tool

The `status_recap` tool demonstrates inter-tool calling by aggregating data from 7+ tools:

```python
# Get weather
weather_result = call_tool('weather', {'location': 'Hillsboro, OR'})

# Get crypto prices
for coin in ['bitcoin', 'solana']:
    crypto_result = call_tool('crypto_price', {'coin': coin})

# Get stock prices
for symbol in ['TSLA', 'GC=F']:
    stock_result = call_tool('stock_price', {'symbol': symbol})

# Generate dashboard image
img_result = call_tool('generate_image', {'prompt': '...'})
```

### Loop Prevention

The environment variable `JARVIS_TOOL_BUILDER_CONTEXT=true` is set when Jarvis is called from the tool builder. This prevents:
- Auto-evolution from triggering
- Tool building from triggering (recursive)

---

### Local Mode

Works with Ollama:

```bash
# config/local.env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3.5:latest

# Tool builder will use Ollama
./bin/build-tool --mode local build "Check CPU temperature"
```

---

## Report Cards & Traceability

Every auto-generated tool has a `tool_name.report.json`:

```json
{
  "tool_name": "text_case_converter",
  "created_at": "2025-12-01T12:00:00",
  "created_by": "auto_builder",
  "mode": "cloud",
  
  "gap_description": "Convert text to uppercase or lowercase",
  "purpose": "Fills the gap for text case conversion operations",
  "feedback_ids": ["fb_001", "fb_002"],
  "evolution_ids": [],
  
  "capabilities": [
    "Convert text to uppercase",
    "Convert text to lowercase"
  ],
  
  "verification_passed": true,
  "verification_output": "All checks passed",
  "test_input_used": {"text": "hello", "case_type": "upper"},
  "test_output": "{\"ok\": true, ...}",
  
  "packages_required": [],
  "packages_new": [],
  
  "mcp_alternatives_checked": ["mcp_...", "..."],
  "mcp_overlap_reason": "No suitable MCP tool found",
  
  "builder_provider": "anthropic",
  "builder_model": "claude-sonnet-4-5-20250929",
  "generation_retries": 0
}
```

---

## Directory Structure

```
skills/
├── *.py                      # Human-created tools
├── *.tool.json              
├── auto-tools/               # Auto-generated tools
│   ├── docker_control.py     # Docker management
│   ├── network_tools.py      # Ping, DNS, port scan
│   ├── status_recap.py       # Comprehensive status briefing
│   ├── system_monitor.py     # CPU, RAM, disk stats
│   ├── text_summarizer.py    # Text summarization
│   ├── youtube_transcript.py # YouTube transcript download
│   └── *.report.json         # Report cards
└── pending/                  # Tools needing approval
    ├── new_tool.py
    ├── new_tool.tool.json
    └── new_tool.report.json

logs/tool-builder/
├── tool-builder-YYYY-MM-DD.jsonl      # Creation logs
└── ouroboros-research-YYYY-MM-DD.jsonl # Research logs
```

### Auto-Generated Tools (as of Jan 2026)

| Tool | Purpose | Key Features |
|------|---------|--------------|
| `docker_control` | Manage Docker containers | List, start, stop, logs, exec |
| `network_tools` | Network diagnostics | Ping, DNS lookup, port scan, traceroute |
| `status_recap` | Comprehensive briefing | Weather, crypto, stocks, alerts, system |
| `system_monitor` | System metrics | CPU, RAM, disk, network, processes |
| `text_summarizer` | Text processing | Summarize, extract keywords, counts |
| `youtube_transcript` | YouTube transcripts | Download as .srt or .md |

---

## Grafana Monitoring

### Labels Available

```yaml
log_type: tool_builder
event: tool_created
tool_name: text_case_converter
status: created | pending_review | failed
mode: cloud | local
verification_passed: true | false
builder_provider: anthropic | openai | ollama
```

### LogQL Queries

```logql
# All tool creation events
{job="jarvis", log_type="tool_builder"} | json

# Failed builds
{job="jarvis", log_type="tool_builder"} | json | status="failed"

# Tools pending approval
{job="jarvis", log_type="tool_builder"} | json | status="pending_review"

# Build success rate
sum(count_over_time({job="jarvis", log_type="tool_builder"} | json | verification_passed="true" [24h]))
/
sum(count_over_time({job="jarvis", log_type="tool_builder"} [24h]))
```

---

## Example: Full Flow

```bash
# 1. Run feedback on a query that reveals a gap
./orchestrator/orchestrator_v2.py cloud "convert hello to uppercase" --feedback
# Feedback: "No tool for text case conversion, had to explain manually"

# 2. Run evolution check (detects gap)
./bin/evolve-prompts --mode cloud check
# Step 5: Found 1 capability gap: "text case conversion"

# 3. Auto-build (or manual)
./bin/build-tool --mode cloud build "Convert text to uppercase or lowercase"

# 4. Sync to enable
./bin/sync_tools.py cloud

# 5. Verify it works
./orchestrator/orchestrator_v2.py cloud "convert hello to uppercase"
# Uses: text_case_converter ✅
```

---

## Dashboard Commands

From `jarvis-dashboard`:

- **Testing → Build Tool** - Build a tool from description
- **Testing → List Pending** - View tools awaiting approval
- **Maint → Sync Tools (Cloud/Local)** - Sync after tool creation

---

## Troubleshooting

### Tool not appearing after creation

```bash
# Sync to vector DB
./bin/sync_tools.py cloud
```

### Verification failed

Check the error message - common issues:
- Missing import (use only available packages)
- Wrong sys.path (auto-tools need `'..', '..', 'lib'`)
- Invalid JSON output

### Network/Connection errors (3 retries all failed)

If you see errors like:
- "Failed to connect to yahoo.com"
- "Connection refused"
- "Read timed out"

The tool builder should auto-inject proxy instructions on retry. If it still fails:

1. Check `LOCAL_PROXY` (and optional `LOCAL_PROXY2`) in `config/cloud.env` or `config/local.env` — see [NETWORK_PROXY.md](NETWORK_PROXY.md)
2. Manually add proxy support using one of the patterns in the BUILD_PROMPT
3. Test the API directly with proxy:
   ```python
   import os
   os.environ['http_proxy'] = 'http://user:pass@host:port'
   os.environ['https_proxy'] = 'http://user:pass@host:port'
   import yfinance as yf
   yf.Ticker('AAPL').history(period='1d')
   ```

### Pending tool approval

```bash
# List pending
./bin/build-tool list-pending

# View details
./bin/build-tool info my_tool

# Install deps and approve
pip install package_name
./bin/build-tool approve my_tool
```

### Tool calls other tools incorrectly

Check the BUILD_PROMPT's "Known Tool Response Structures" section:
- `stash` returns `data.ref`, not `data.stash_ref`
- `generate_image` returns `data.saved.stash_ref` (nested!)
- Always use `cwd=project_root` in subprocess.run()

### JSON parse error with python_code (Fixed in v2.1)

If you previously saw errors like:
```
Failed to parse JSON: Expecting ',' delimiter: line 14 column 12156
```

This was caused by LLMs generating Python code with literal newlines instead of `\n` escapes.
**This is now automatically fixed** by `_extract_python_code_field()` in tool_builder.py.

---

## Grafana Monitoring

A dedicated dashboard is available at:

**Dashboard**: [Jarvis Tool Builder](http://localhost:3000/d/jarvis-tool-builder)

### Panels

| Panel | Description |
|-------|-------------|
| 🔧 Tools Created | Total tools built |
| 🐍 Ouroboros Research | Research calls made |
| ✅ Success Rate | Verification pass rate |
| ⏱️ Avg Research Duration | How long research takes |
| ⏳ Pending Tools | Awaiting approval |
| ❌ Skipped | Duplicates/trivial filtered |

### Log Streams

- **Tool Builder Logs** - Real-time creation events
- **Ouroboros Research Logs** - Research queries and results

### LogQL Queries

```logql
# All tool creations
{job="jarvis", log_type="tool_builder"} |= "tool_created"

# Research calls
{job="jarvis", log_type="ouroboros"} | json

# Failed builds
{job="jarvis", log_type="tool_builder"} |= "failed"

# Skipped duplicates
{job="jarvis", log_type="tool_builder"} |= "skipped_duplicate"
```

---

## Limitations & Future Improvements

### Current Limitations

| Limitation | Status | Workaround |
|-----------|--------|------------|
| **Python only** | By design | Tools can call external CLIs via subprocess |
| ~~One-shot generation~~ | ✅ **DONE** | Retries with error context + smart analysis |
| ~~No web search~~ | ✅ **DONE** | Ouroboros pattern - calls Jarvis for research |
| ~~No tool access~~ | ✅ **DONE** | Uses Jarvis's existing tools via Ouroboros |
| **Manual API key setup** | By design | Shows required env vars in pending |
| ~~No duplicate check~~ | ✅ **DONE** | Checks ALL existing tools before building |
| ~~Network errors~~ | ✅ **DONE** | Auto-detects and injects proxy fix instructions |
| ~~Inter-tool calling~~ | ✅ **DONE** | BUILD_PROMPT documents correct patterns |
| ~~JSON parse errors~~ | ✅ **DONE** | v2.1 - Robust python_code field extraction |

### Planned Enhancements

1. **Test Coverage**
   - Run tool in isolated container
   - Multiple test cases, not just one
   
2. **Smart API Key Detection**
   - Auto-detect if similar API already configured
   - Suggest reusing existing credentials
   
3. **Auto-Dependency Resolution**
   - Auto-approve safe packages from allowlist
   - Better pip install handling

### Python-Only Is Actually Powerful

Python can:
- Call any CLI tool via `subprocess`
- Make HTTP requests to any API
- Parse HTML, JSON, XML, etc.
- Do file operations
- Connect to databases

Most "tools" are really just API wrappers or CLI utilities - Python handles these perfectly.

