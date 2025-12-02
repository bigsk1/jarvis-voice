# Jarvis Tool Builder - Autonomous Tool Creation

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
- Standard library: `os`, `sys`, `json`, `re`, `datetime`, etc.
- Already installed: `requests`, `pint`, `flask`, `beautifulsoup4`, etc.

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

### 5. Retry Loop

If verification fails, the LLM gets 3 attempts with error feedback to fix it.

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
TOOL_BUILDER_PROVIDER=anthropic
TOOL_BUILDER_MODEL=claude-sonnet-4-5-20250929

# Or falls back to feedback provider
FEEDBACK_PROVIDER=anthropic
FEEDBACK_MODEL=claude-sonnet-4-5-20250929
```

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
OLLAMA_MODEL=qwen3:14b

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
│   ├── text_case_converter.py
│   ├── text_case_converter.tool.json
│   └── text_case_converter.report.json
└── pending/                  # Tools needing approval
    ├── new_tool.py
    ├── new_tool.tool.json
    └── new_tool.report.json

logs/tool-builder/
└── tool-builder-YYYY-MM-DD.jsonl  # Creation logs
```

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

---

## Grafana Monitoring

A dedicated dashboard is available at:

**Dashboard**: [Jarvis Tool Builder](http://192.168.70.228:3000/d/jarvis-tool-builder)

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
| **One-shot generation** | Working on | Retries for JSON parsing, not for logic errors |
| ~~No web search~~ | ✅ **DONE** | Ouroboros pattern - calls Jarvis for research |
| ~~No tool access~~ | ✅ **DONE** | Uses Jarvis's existing tools via Ouroboros |
| **Manual API key setup** | By design | Shows required env vars in pending |
| ~~No duplicate check~~ | ✅ **DONE** | Checks ALL existing tools before building |

### Planned Enhancements

1. **Iterative Building**
   - If verification fails, send error back to LLM
   - Let it fix the code instead of regenerating
   
2. **Test Coverage**
   - Run tool in isolated container
   - Multiple test cases, not just one
   
3. **Smart API Key Detection**
   - Auto-detect if similar API already configured
   - Suggest reusing existing credentials

### Python-Only Is Actually Powerful

Python can:
- Call any CLI tool via `subprocess`
- Make HTTP requests to any API
- Parse HTML, JSON, XML, etc.
- Do file operations
- Connect to databases

Most "tools" are really just API wrappers or CLI utilities - Python handles these perfectly.

