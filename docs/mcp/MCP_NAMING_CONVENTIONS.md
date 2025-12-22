# MCP Naming Conventions

## Critical Rule: Use snake_case for All MCP Server Names

### Why snake_case?

**TL;DR**: Local LLMs get confused with hyphens and camelCase. snake_case works reliably with ALL models.

### Tested Naming Conventions

| Naming Style | Example | Cloud Models | Local Models | Verdict |
|--------------|---------|--------------|--------------|---------|
| **snake_case** | `brave_search` | ✅ Works | ✅ Works | ✅ **USE THIS** |
| kebab-case | `brave-search` | ✅ Works | ❌ Confused | ❌ Avoid |
| camelCase | `braveSearch` | ✅ Works | ❌ Confused | ❌ Avoid |
| PascalCase | `BraveSearch` | ✅ Works | ❌ Confused | ❌ Avoid |

### Real-World Evidence

From previous testing sessions:
- **Qwen models** (qwen3:14b, qwen3-coder): Struggled with `brave-search`, worked perfectly with `brave_search`
- **Mistral models**: Similar behavior - prefer underscores
- **Claude/GPT**: Handle all formats but snake_case maintains consistency

### Tool Name Format

All MCP tools follow this format:
```
mcp_{server_name}_{tool_name}
```

Examples:
- ✅ `mcp_brave_search_brave_web_search`
- ✅ `mcp_fetch_fetch`
- ✅ `mcp_sequential_thinking_analyze`
- ❌ `mcp_brave-search_web-search` (hyphens cause parsing issues)

### Configuration Example

```json
{
  "mcpServers": {
    "brave_search": {
      "command": "docker",
      "args": ["run", "-e", "BRAVE_API_KEY", "-i", "--rm", "--network", "host", "mcp/brave-search"],
      "env": {
        "BRAVE_API_KEY": "${BRAVE_API_KEY}"
      },
      "enabled": true
    },
    "sequential_thinking": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/sequentialthinking"],
      "enabled": false
    }
  }
}
```

**Note**: The Docker image name (e.g., `mcp/brave-search`) can use hyphens. Only the JSON key (server name) must use snake_case.

### Why This Matters

1. **Consistency**: One naming convention across all modes (cloud/local)
2. **Reliability**: Local models have higher success rate with tool calling
3. **Maintainability**: No special cases or mode-specific workarounds
4. **Future-proof**: Works with any LLM provider

### When Adding New MCP Servers

✅ **DO**:
```json
"my_custom_server": { ... }
"web_scraper_advanced": { ... }
"data_analyzer_pro": { ... }
```

❌ **DON'T**:
```json
"my-custom-server": { ... }       // Hyphens
"webScraperAdvanced": { ... }     // camelCase  
"DataAnalyzerPro": { ... }        // PascalCase
```

### Related Files

- `config/mcp-servers.json` - MCP server configuration
- `lib/tool_schema.py` - Tool discovery and parsing (see `get_mcp_info()`)
- `lib/mcp_client.py` - MCP client implementation
- `docs/MCP_REGRESSION_FIX.md` - Recent regression analysis

### References

- Original issue: Testing showed local models confused by hyphenated names
- Architecture decision: Enforce snake_case for local model compatibility
- Implementation: `get_mcp_info()` dynamically handles any snake_case name with underscores

