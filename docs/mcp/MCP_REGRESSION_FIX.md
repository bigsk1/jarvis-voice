# MCP Brave Search Regression Fix (Nov 2025)

## Problem

Brave MCP server was working previously but stopped functioning with error:
```
MCP server brave not available. Server may have failed to start.
```

## Root Cause

The `get_mcp_info()` function in `lib/tool_schema.py` was using simple string splitting:
```python
# OLD (BROKEN) CODE:
parts = tool_name[4:].split("_", 1)  # Split on first underscore
```

This broke when MCP server names contained underscores:
- Tool name: `mcp_brave_search_brave_web_search`
- Parsed as: `server="brave"` (❌ WRONG! Should be "brave_search")
- Result: Executor looked for client "brave" which doesn't exist

## Solution

Dynamically match against registered MCP clients:
```python
# NEW (FIXED) CODE:
for server_name in sorted(self.mcp_clients.keys(), key=len, reverse=True):
    if remaining.startswith(server_name + "_"):
        mcp_tool_name = remaining[len(server_name) + 1:]
        return server_name, mcp_tool_name
```

### Why This Works

1. **Dynamic**: No hardcoded server names - works with ANY MCP server
2. **Supports underscores**: Correctly handles `brave_search`, `sequential_thinking`, etc.
3. **Longest match first**: If you had both "brave" and "brave_search", matches longest
4. **Add any server**: Just add to `mcp-servers.json` and it works automatically

### Test Cases

| Tool Name | Parsed Server | Parsed Tool | Status |
|-----------|---------------|-------------|--------|
| `mcp_brave_search_brave_web_search` | `brave_search` | `brave_web_search` | ✅ |
| `mcp_fetch_fetch` | `fetch` | `fetch` | ✅ |
| `mcp_my_custom_server_name_tool` | `my_custom_server_name` | `tool` | ✅ |

## Prevention

Added comprehensive documentation to `get_mcp_info()`:
- **CRITICAL** warning at function start
- Examples showing underscore handling
- Explanation of why simple splitting breaks
- Regression risk clearly stated

## Verification

1. **Manual test**: Brave search works in orchestrator
   ```bash
   ./orchestrator/orchestrator_v2.py cloud "Use brave web search to find OpenAI"
   # ✅ Returns OpenAI results
   ```

2. **Automated test**: Focused MCP tests pass
   ```bash
   ~/jarvis-venv/bin/python -m pytest -q \
     tests/test_mcp_discovery_graceful.py \
     tests/test_mcp_env_substitution.py
   ```

3. **MCP integration test**:
   ```bash
   ./tests/test_mcp_docker_integration.sh
   # ✅ Verifies API keys pass to Docker containers
   ```

4. **Dynamic test**: Added fake server to prove no hardcoding
   ```python
   registry.mcp_clients["my_new_server_with_underscores"] = None
   # ✅ Correctly parses: mcp_my_new_server_with_underscores_tool
   ```

## Files Changed

- `lib/tool_schema.py` - Fixed `get_mcp_info()` with comprehensive docs
- `docs/mcp/MCP_REGRESSION_FIX.md` - This document

## Key Takeaways

### 1. Never Simplify `get_mcp_info()` to Use String Splitting

The dynamic matching against `self.mcp_clients.keys()` is the ONLY way to support:
- Server names with underscores (like `brave_search`)
- Any new MCP server added to `mcp-servers.json`
- Future-proof architecture

### 2. MCP Server Names MUST Use snake_case (Underscores)

**ARCHITECTURAL DECISION**: This is intentional, not accidental!

- ✅ **snake_case**: `brave_search`, `sequential_thinking` (LOCAL MODELS UNDERSTAND)
- ❌ **kebab-case**: `brave-search` (local models get confused)
- ❌ **camelCase**: `braveSearch` (local models get confused)

**Historical Context**: Previous testing showed local LLMs (Ollama, etc.) have trouble with tool names using hyphens or camelCase. They consistently perform better with snake_case naming.

**Why This Matters**:
- Cloud models (Claude, GPT) handle any naming convention
- Local models (Qwen, Mistral, etc.) need snake_case for reliable tool calling
- Consistency across all MCP servers improves LLM accuracy
- This decision was made based on real-world testing with local models

**Enforcement**: All MCP server names in `config/mcp-servers.json` should use snake_case.

## Related

- See `lib/tool_schema.py` line ~350 for implementation
- See `tests/test_mcp_docker_integration.sh` for integration tests
- See `config/mcp-servers.json` for server configuration
