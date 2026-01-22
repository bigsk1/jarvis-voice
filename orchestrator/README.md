# Orchestrator

The orchestrator is the "brain" of Jarvis that:
1. **Routes** user queries via LLM analysis
2. **Executes** tools/skills with multi-turn support
3. **Runs** deterministic workflow pipelines
4. **Formats** responses for voice/text output

---

## Architecture

```
User Query
    ↓
┌───────────────────────────────────────────────┐
│              orchestrator_v2.py               │
│  (main coordinator - handles all routing)     │
└───────────────────────────────────────────────┘
    ↓
┌───────────────────┐     ┌─────────────────────┐
│  Workflow Check   │────→│  pipeline_executor  │
│  (explicit /cmd)  │     │  (deterministic)    │
└───────────────────┘     └─────────────────────┘
    ↓ (if not workflow)
┌───────────────────┐
│    router_v2.py   │
│  (LLM analysis)   │
└───────────────────┘
    ↓
┌─────────┬─────────┐
│  Tool   │   Q&A   │
│  Call   │Response │
└─────────┴─────────┘
    ↓
┌───────────────────┐
│   executor.py     │
│  (runs skills/)   │
└───────────────────┘
```

---

## Components

### `orchestrator_v2.py` (Main Entry Point)
The primary orchestration script. Handles:
- Mode selection (cloud/local)
- Workflow detection and execution
- LLM routing for tool selection
- Multi-turn orchestration (chains tools automatically)
- Intelligence layer integration
- Cost tracking and logging

```bash
# Usage
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py local "Search for Python tutorials"
./orchestrator/orchestrator_v2.py cloud "/crypto"  # Triggers workflow
```

### `router_v2.py` (LLM-Based Router)
Analyzes user queries and determines:
- Whether to call a tool or respond directly
- Which tool(s) to use
- Parameters to extract from the query
- Uses Tool RAG for dynamic tool discovery

Returns routing decisions with tool selections and arguments.

### `executor.py` (Tool Executor)
Executes tools/skills from `skills/` and `skills/auto-tools/`:
- Manages timeouts and error handling
- Handles JSON I/O with tools
- Supports MCP server tools
- Returns: `{ok, speech, data}`

### `pipeline_executor.py` (Workflow Engine)
Executes deterministic workflow pipelines:
- Loads workflow definitions from `data/workflows/*.json`
- Runs tools in predefined sequence
- Handles variable substitution between steps
- LLM parameter filling for dynamic values
- Content validation and retry logic
- Bypasses normal LLM routing

### `workflow_loader.py` (Workflow Loader)
Loads and validates workflow JSON definitions:
- Discovers workflows from `data/workflows/`
- Validates required fields (id, trigger, steps)
- Provides workflow metadata for API/UI

### Legacy Files
- `orchestrator.py` - Original orchestrator (deprecated, kept for reference)
- `router.py` - Original rule-based router (deprecated, kept for reference)

---

## Two Execution Paths

### 1. LLM Routing (Default)
For general queries, the LLM analyzes and selects tools:

```
"What's the weather?" → router_v2 → weather tool → response
"Build a Flask API"  → router_v2 → opencode → multi-turn → response
```

### 2. Workflow Pipelines (Explicit Commands)
For `/commands`, deterministic execution:

```
"/crypto"     → pipeline_executor → [get_time, crypto_price, search, ...] → response
"/archive X"  → pipeline_executor → [crawl_url, stash, remember, canvas] → response
```

---

## Usage Examples

### CLI Queries
```bash
# Cloud mode (xAI/Anthropic/OpenAI)
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py cloud "Remember my server IP is 192.168.1.100"

# Local mode (Ollama)
./orchestrator/orchestrator_v2.py local "Search for Python tutorials"

# With debug output
./orchestrator/orchestrator_v2.py cloud "What's the weather?" --debug
```

### Workflow Execution
```bash
# Crypto market report
./orchestrator/orchestrator_v2.py cloud "/crypto"

# Web archive
./orchestrator/orchestrator_v2.py cloud "/archive https://example.com"

# Deep research
./orchestrator/orchestrator_v2.py cloud "/research AI trends 2026"

# Quick note
./orchestrator/orchestrator_v2.py cloud "/note Remember to check logs"

# Server health (SSH)
./orchestrator/orchestrator_v2.py cloud "/health vps2"
```


**Exit Code**: 0 for success, non-zero for error

---

## Configuration

Key environment variables (in `config/cloud.env` or `config/local.env`):


---

## Related Documentation

- **[WORKFLOW_ORCHESTRATION.md](../docs/WORKFLOW_ORCHESTRATION.md)** - Full workflow system
- **[TOOL_CALLING_SYSTEM.md](../docs/TOOL_CALLING_SYSTEM.md)** - How tool routing works
- **[JARVIS_WORKFLOW.md](../docs/JARVIS_WORKFLOW.md)** - Complete request flow
- **[INTELLIGENCE_LAYER.md](../docs/INTELLIGENCE_LAYER.md)** - Self-learning system
- **[api/WORKFLOWS.md](../docs/api/WORKFLOWS.md)** - Workflows API reference
