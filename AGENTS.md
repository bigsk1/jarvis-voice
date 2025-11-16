# Agent Guidelines for Jarvis Voice Assistant

> **Purpose**: This document provides coding standards, architectural patterns, and best practices for developing Jarvis Voice Assistant. Follow these guidelines to ensure consistency, maintainability, and compatibility with the existing codebase.

---

## 📋 Table of Contents

1. [Quick Reference](#quick-reference)
2. [Project Architecture](#project-architecture)
3. [Code Style Standards](#code-style-standards)
4. [Tool Development](#tool-development)
5. [Memory System Patterns](#memory-system-patterns)
6. [Configuration Management](#configuration-management)
7. [Testing Requirements](#testing-requirements)
8. [Documentation Standards](#documentation-standards)
9. [Common Patterns](#common-patterns)
10. [Anti-Patterns (Avoid These)](#anti-patterns-avoid-these)

---

## Quick Reference

### Testing & Running
```bash
# Single tool test
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py local "What time is it?"

# Comprehensive tests
./test-all-tools.sh        # Cloud mode (OpenAI/Anthropic)
./test-all-tools-local.sh  # Local mode (Ollama)

# Memory system tests
./tests/integration/test-memory-tools.sh        # Tool selection
./tests/integration/test-memory-real-world.sh   # Complex scenarios

# Model comparison
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b

# Voice mode
./jarvis        # Cloud mode
./jarvis-local  # Local mode
```

### File Locations Quick Map
```
skills/              → Tool scripts + JSON definitions
lib/                 → Core libraries (memory_db, llm_provider, etc.)
orchestrator/        → Routing and orchestration logic
config/              → .env files (cloud.env, local.env)
data/                → Databases (jarvis_memory.db, jarvis_memory_local.db)
docs/                → Documentation (organized by feature)
tests/integration/   → Integration tests + model comparison
bin/                 → Utility scripts (manage-tools, sync-memory-db)
```

---

## Project Architecture

### System Overview

```
User Query
    ↓
Orchestrator (orchestrator_v2.py)
    ↓
Router (router_v2.py) - Analyzes intent, selects tools
    ↓
Executor (executor.py) - Runs tools, handles errors
    ↓
Tool Script (skills/*.py)
    ↓
Response → User
```

### Dual Database Architecture

**CRITICAL**: Jarvis uses **separate databases** for cloud and local modes:
- `data/jarvis_memory.db` - Cloud mode (OpenAI embeddings, 1536-dim)
- `data/jarvis_memory_local.db` - Local mode (nomic-embed-text, 768-dim)

**Why**: Embedding models are incompatible. Auto-sync on startup ensures shared memories.

See: `docs/DUAL_DATABASE_SYSTEM.md`

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| **Orchestrator** | `orchestrator/orchestrator_v2.py` | Main entry point, multi-turn logic |
| **Router** | `orchestrator/router_v2.py` | LLM-based tool selection |
| **Executor** | `orchestrator/executor.py` | Tool execution, error handling |
| **Tool Registry** | `lib/tool_schema.py` | Tool discovery, enable/disable |
| **Memory DB** | `lib/memory_db.py` | SQLite with semantic search |
| **LLM Provider** | `lib/llm_provider.py` | Abstraction for OpenAI/Anthropic/Ollama |
| **Config Loader** | `lib/config_loader.py` | Environment variable management |

---

## Code Style Standards

### Import Order
```python
# 1. Standard library
import os
import json
import sys
from datetime import datetime

# 2. Third-party packages
import requests
from anthropic import Anthropic

# 3. Local modules (with explicit path)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from memory_db import MemoryDB
from config_loader import load_config, get_config_value
```

### Type Hints (Required for Public Functions)
```python
from typing import Dict, Any, Optional, List

def process_data(input_text: str, limit: int = 5) -> Dict[str, Any]:
    """Process data and return result."""
    pass

# Optional for simple internal functions
def _helper(x):
    return x * 2
```

### Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| **Functions** | snake_case | `search_memory()`, `get_time()` |
| **Variables** | snake_case | `user_query`, `memory_count` |
| **Classes** | PascalCase | `MemoryDB`, `ToolSchema` |
| **Constants** | UPPER_CASE | `MAX_RETRIES`, `DEFAULT_LIMIT` |
| **Private** | _leading_underscore | `_internal_helper()` |
| **Tool scripts** | lowercase_with_underscores.py | `search_memory.py` |
| **Tool JSON** | lowercase_with_underscores.tool.json | `search_memory.tool.json` |

### Formatting
- **Indentation**: 4 spaces (no tabs)
- **Line length**: No hard limit (readability over arbitrary limits)
- **Docstrings**: Use for public functions, classes
- **Comments**: Explain "why", not "what"

### Error Handling Pattern
```python
# Tools MUST return this format
def main():
    try:
        # Tool logic here
        result = do_something()
        
        print(json.dumps({
            "ok": True,
            "speech": "Task completed successfully",
            "data": result
        }))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed: {e}"
        }))
        sys.exit(1)
```

---

## Tool Development

### Tool Structure (Required Files)

Every tool needs TWO files in `skills/`:

1. **Python script** (`tool_name.py`)
2. **JSON definition** (`tool_name.tool.json`)

### Tool Script Template

```python
#!/usr/bin/env python3
"""
Tool Name: Description of what this tool does
Input: { "param": "value" }
Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value

def main():
    try:
        # Parse arguments (from stdin or argv)
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config for current mode (auto-detected)
        load_config()  # Loads based on LLM_PROVIDER env var
        
        # Extract parameters with validation
        required_param = args.get('required_param')
        if not required_param:
            raise ValueError("required_param is missing")
        
        optional_param = args.get('optional_param', 'default_value')
        
        # Tool logic here
        result = do_work(required_param, optional_param)
        
        # ALWAYS return this format
        print(json.dumps({
            "ok": True,
            "speech": f"Successfully processed {required_param}",
            "data": result
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Error: {e}"
        }))
        sys.exit(1)

def do_work(param1: str, param2: str) -> Dict[str, Any]:
    """Actual tool logic (separate for testing)."""
    return {"result": "data"}

if __name__ == "__main__":
    main()
```

### Tool JSON Template

```json
{
  "enabled": true,
  "name": "tool_name",
  "description": "Clear description for LLM. Explain WHEN to use this tool and what it does. Include examples if helpful.",
  "script": "tool_name.py",
  "parameters": {
    "type": "object",
    "properties": {
      "required_param": {
        "type": "string",
        "description": "What this parameter does"
      },
      "optional_param": {
        "type": "string",
        "description": "Optional parameter with default"
      }
    },
    "required": ["required_param"]
  },
  "permissions": {
    "dangerous": false,
    "bash": false,
    "network": true,
    "filesystem": false,
    "auto_approve": true
  }
}
```

### Tool Description Guidelines

**GOOD** (specific, actionable):
```json
"description": "Keyword search in stored memories (fuzzy text matching). Finds memories where the key or value contains your search term. Use for simple keyword lookups. For natural language questions, use semantic_recall instead. Example: query='food' finds 'favorite_food', 'seafood', etc."
```

**BAD** (vague):
```json
"description": "Search memories"
```

### Enable/Disable Tools

```bash
# Manage tool availability
./bin/manage-tools.py list
./bin/manage-tools.py disable crypto_price
./bin/manage-tools.py enable crypto_price

# In tool.json
{
  "enabled": true,  # Set to false to disable without deleting code
  ...
}
```

---

## Memory System Patterns

### Database Selection (Automatic)

```python
from memory_db import MemoryDB

# DO THIS (auto-detects mode based on LLM_PROVIDER)
db = MemoryDB()  # Uses jarvis_memory_local.db if ollama, jarvis_memory.db otherwise

# DON'T hardcode paths
db = MemoryDB("data/jarvis_memory.db")  # BAD - breaks dual-DB system
```

### Memory Operations

```python
from memory_db import MemoryDB

db = MemoryDB()

# Save memory
db.remember(
    key="project_location",
    value="Flask API at ~/jarvis-workspace/projects/flask-api",
    category="technical",
    importance=8
)

# Keyword search (SQL LIKE)
memories = db.search_memory(query="flask", limit=10)

# Semantic search (AI embeddings)
memories = db.semantic_search(query="Where is my web app?", limit=5)

# Get recent conversations
conversations = db.get_recent_conversations(limit=10)
```

### When to Use Which Search

| Search Type | Tool | Use Case | Example |
|-------------|------|----------|---------|
| **Keyword** | `search_memory` | 1-3 word lookups | "flask", "webhook", "tetris" |
| **Semantic** | `semantic_recall` | Natural language questions (4+ words) | "Where is my web application?" |
| **Conversation** | `search_conversations` | Past interactions | "What did I ask about yesterday?" |

### Semantic Threshold Tuning

```bash
# In config/cloud.env or config/local.env
SEMANTIC_SIMILARITY_THRESHOLD=0.40  # Default (balanced)
# 0.30-0.35 = More results (loose matching)
# 0.40-0.45 = Balanced (recommended)
# 0.50+     = Fewer results (strict matching)
```

See: `docs/SEMANTIC_THRESHOLD_TUNING.md`

---

## Configuration Management

### Loading Config (Required Pattern)

```python
from config_loader import load_config, get_config_value, get_int, get_float

# At startup (in main entry point like orchestrator)
load_config(mode='cloud')  # or 'local'

# In tools (auto-detect mode)
load_config()  # Detects mode from LLM_PROVIDER env var

# Get values
api_key = get_config_value('ANTHROPIC_API_KEY')
timeout = get_int('REQUEST_TIMEOUT', 90)
threshold = get_float('SEMANTIC_SIMILARITY_THRESHOLD', 0.40)
```

### Config File Organization

```
config/
├── cloud.env         # Production config (gitignored)
├── local.env         # Production config (gitignored)
├── cloud.env.example # Template (safe for git)
└── local.env.example # Template (safe for git)
```

**NEVER commit** `cloud.env` or `local.env` (contains API keys)

### Key Config Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `LLM_PROVIDER` | Main LLM | `anthropic`, `openai`, `ollama` |
| `ANTHROPIC_MODEL` | Claude model | `claude-sonnet-4-5-20250929` |
| `OLLAMA_MODEL` | Local model | `qwen3-vl`, `qwen2.5:7b` |
| `OPENCODE_PROVIDER` | OpenCode LLM | `anthropic` (recommended) |
| `SEMANTIC_SIMILARITY_THRESHOLD` | Search sensitivity | `0.40` |
| `JARVIS_RESPONSE_STYLE` | Output format | `auto`, `casual`, `detailed` |

---

## Testing Requirements

### Test Types

```bash
# Integration tests (required for new tools)
./test-all-tools.sh                                  # All tools (cloud)
./test-all-tools-local.sh                            # All tools (local)

# Memory tests
./tests/integration/test-memory-tools.sh             # Tool selection principles
./tests/integration/test-memory-real-world.sh        # Complex scenarios

# Model comparison (performance analysis)
./tests/integration/compare-models.sh local qwen3-vl qwen2.5:7b

# Single tool test (during development)
./orchestrator/orchestrator_v2.py cloud "use my_tool with X"
```

### Writing Tests

When adding a new tool, add test cases to:
- `test-all-tools.sh` (if cloud-compatible)
- `test-all-tools-local.sh` (if local-compatible)

Format:
```bash
echo "Test: tool_name"
echo "Query: Use tool_name to do X"
OUTPUT=$(./orchestrator/orchestrator_v2.py cloud "Use tool_name to do X")
if echo "$OUTPUT" | grep -q "expected_keyword"; then
    echo "✅ PASSED"
else
    echo "❌ FAILED"
fi
```

---

## Documentation Standards

### When to Document

- **New features**: Update main README + create feature doc in `docs/`
- **Tool changes**: Update tool.json description
- **API changes**: Update relevant docs in `docs/`
- **Bug fixes**: Update FIXES log if significant

### Documentation Structure

```
docs/
├── QUICKSTART.md              # Getting started
├── MEMORY_SYSTEM.md           # Memory architecture
├── DUAL_DATABASE_SYSTEM.md    # Cloud/local DB system
├── TOOL_MANAGEMENT.md         # Enable/disable tools
├── opencode/                  # OpenCode docs (organized)
│   ├── OPENCODE.md
│   ├── OPENCODE_API_REFERENCE.md
│   └── ...
└── archive/                   # Historical docs
    └── ...
```

### Doc File Naming

- `FEATURE_NAME.md` - Main feature docs (UPPER_CASE)
- Descriptive names (e.g., `SEMANTIC_THRESHOLD_TUNING.md`)
- No dates in filename (use git history)

---

## Common Patterns

### 1. Multi-Turn Tool Orchestration

Tools can call other tools:
```python
# Orchestrator handles this automatically
# User: "Build a Flask API and test it"
# Turn 1: opencode → Build Flask API
# Turn 2: api_call → Test endpoint
# Turn 3: Q&A response → "Flask API running on port 8091"
```

### 2. Memory Auto-Save

```python
# After completing a task, save important info
if task_completed and has_persistent_value:
    db.remember(
        key="project_location",
        value=f"Project at {path}",
        category="technical",
        importance=8
    )
```

### 3. Error Recovery

```python
# Orchestrator retries failed tools
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        result = execute_tool(tool, args)
        break
    except Exception as e:
        if attempt == MAX_RETRIES - 1:
            raise
        time.sleep(2 ** attempt)  # Exponential backoff
```

### 4. Config-Based Behavior

```python
# Adapt behavior based on mode
if get_config_value('LLM_PROVIDER') == 'ollama':
    timeout = 180  # Local models need more time
    context_window = 32768  # Smaller for local
else:
    timeout = 90
    context_window = 200000  # Claude has huge context
```

---

## Anti-Patterns (Avoid These)

### ❌ Hardcoding Database Paths

```python
# BAD
db = MemoryDB("data/jarvis_memory.db")

# GOOD
db = MemoryDB()  # Auto-selects based on mode
```

### ❌ Not Using Config Loader

```python
# BAD
api_key = os.environ.get('ANTHROPIC_API_KEY')

# GOOD
from config_loader import get_config_value
api_key = get_config_value('ANTHROPIC_API_KEY')
```

### ❌ Returning Wrong Format from Tools

```python
# BAD
print("Task completed")  # Plain text
return {"result": "data"}  # Python object

# GOOD
print(json.dumps({
    "ok": True,
    "speech": "Task completed",
    "data": {"result": "data"}
}))
```

### ❌ Mixing Embedding Models

```python
# BAD - Using OpenAI embeddings in local DB
embedding = openai.embeddings.create(...)
db_local.save_with_embedding(embedding)  # Wrong dimension!

# GOOD - Use mode-appropriate embedding model
from embeddings import get_embedding
embedding = get_embedding(text)  # Auto-selects model
```

### ❌ Vague Tool Descriptions

```json
// BAD
"description": "Search tool"

// GOOD
"description": "Keyword search in memories (SQL LIKE). Use for 1-3 word searches like 'flask', 'webhook'. For questions like 'Where is my app?', use semantic_recall instead."
```

### ❌ Not Handling Missing Parameters

```python
# BAD
query = args['query']  # KeyError if missing

# GOOD
query = args.get('query')
if not query:
    raise ValueError("query parameter is required")
```

### ❌ Breaking Tool Interface

```python
# BAD - Tool doesn't return JSON
def main():
    result = do_work()
    print(result)  # Plain text

# GOOD
def main():
    try:
        result = do_work()
        print(json.dumps({"ok": True, "speech": "Done", "data": result}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)
```

---

## Special Integrations

### OpenCode Integration

```python
# OpenCode works in isolated workspace
OPENCODE_WORKSPACE = "~/jarvis-workspace"

# After OpenCode completes, auto-save location
db.remember(
    key="project_location",
    value=f"Flask API at ~/jarvis-workspace/projects/flask-api on port {port}",
    category="technical",
    importance=8
)
```

See: `docs/opencode/OPENCODE.md`

### MCP Servers

Tools from MCP servers are auto-discovered:
- `mcp_duckduckgo_search` - Web search
- `mcp_fetch_fetch` - HTTP fetch
- Tool names prefixed with `mcp_<server>_<tool>`

See: `docs/MCP_QUICKSTART.md`

---

## Quick Troubleshooting

### Database Issues
```bash
# Check which DB is active
echo $LLM_PROVIDER  # ollama = local.db, else cloud.db

# Manual sync between DBs
./bin/sync-memory-db.py cloud  # Sync from local → cloud
./bin/sync-memory-db.py local  # Sync from cloud → local

# Backup before experiments
cp data/jarvis_memory.db data/jarvis_memory.db.backup
```

### Tool Not Loading
```bash
# Check tool status
./bin/manage-tools.py list

# Enable if disabled
./bin/manage-tools.py enable tool_name

# Check logs
tail -f logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl
```

### Config Not Loading
```bash
# Verify config file exists
ls -la config/cloud.env config/local.env

# Check environment
echo $LLM_PROVIDER

# Test config loading
python3 -c "
import sys
sys.path.insert(0, 'lib')
from config_loader import load_config, get_config_value
load_config('cloud')
print(get_config_value('ANTHROPIC_MODEL'))
"
```

---

## Summary Checklist

Before committing code, verify:

- [ ] Tool scripts return correct JSON format
- [ ] Tool JSON has clear, specific description
- [ ] Used `MemoryDB()` without hardcoded paths
- [ ] Config loaded via `config_loader`
- [ ] Type hints on public functions
- [ ] Error handling with try/except
- [ ] Test added to test-all-tools.sh
- [ ] Documentation updated if feature added
- [ ] Tool marked executable (`chmod +x`)
- [ ] Follows import order (stdlib → 3rd party → local)

---

**Need more details?** See:
- Main README: `/README.md`
- Docs Index: `/docs/README.md`
- Tool System: `/docs/TOOL_CALLING_SYSTEM.md`
- Memory System: `/docs/MEMORY_SYSTEM.md`
