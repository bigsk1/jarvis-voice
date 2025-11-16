# Tool Management System

## Overview

Jarvis now supports enabling/disabling tools dynamically, similar to MCP servers. This allows you to:

- **Reduce token count** for local models (important for Ollama)
- **Improve response speed** by loading fewer tools
- **Create focused profiles** (coding tools only, home automation only, etc.)
- **Easier testing** by temporarily disabling tools

## Quick Start

```bash
# List all tools
./bin/manage-tools.py list

# List with descriptions
./bin/manage-tools.py list -v

# Disable a tool
./bin/manage-tools.py disable execute_bash

# Enable a tool
./bin/manage-tools.py enable execute_bash

# Enable all tools
./bin/manage-tools.py enable-all
```

## How It Works

### Tool Schema Format

Each `*.tool.json` file now has an `enabled` field:

```json
{
  "enabled": true,
  "name": "crypto_price",
  "description": "Get cryptocurrency prices",
  "script": "crypto_price.py",
  "parameters": { ... },
  "permissions": { ... }
}
```

- **`enabled: true`** → Tool loads normally
- **`enabled: false`** → Tool skipped at startup (no memory/token usage)

### Backward Compatibility

- Tools without `enabled` field default to `true`
- All existing tools have been migrated automatically
- No breaking changes to existing code

## Use Cases

### 1. Reduce Token Count for Local Models

Ollama models have limited context windows. Disable unnecessary tools:

```bash
# Keep only essential tools for conversation
./bin/manage-tools.py disable send_webhook
./bin/manage-tools.py disable api_call
./bin/manage-tools.py disable execute_bash
./bin/manage-tools.py disable opencode

# Result: ~6k tokens → ~3k tokens (50% reduction!)
```

### 2. Create Focused Profiles

**Coding Profile** (disable non-coding tools):
```bash
./bin/manage-tools.py disable crypto_price
./bin/manage-tools.py disable send_webhook
# Keep: opencode, execute_bash, memory tools
```

**Home Automation Profile**:
```bash
./bin/manage-tools.py disable opencode
./bin/manage-tools.py disable crypto_price
# Keep: api_call, send_webhook, execute_bash
```

### 3. Testing & Development

```bash
# Disable tools you're not testing
./bin/manage-tools.py disable opencode  # Save 2+ minutes startup time

# Focus on specific tool
./bin/manage-tools.py disable api_call
# ... test other tools ...
./bin/manage-tools.py enable api_call
```

### 4. Security Hardening

```bash
# Disable dangerous tools in production
./bin/manage-tools.py disable execute_bash
./bin/manage-tools.py disable opencode
```

## Implementation Details

### Code Changes

**1. `lib/tool_schema.py`** - Added enable/disable check:
```python
def _discover_tools(self):
    for tool_file in self.skills_dir.glob("*.tool.json"):
        with open(tool_file, 'r') as f:
            tool_config = json.load(f)
        
        # Check if tool is enabled (defaults to True)
        if not tool_config.get('enabled', True):
            print(f"⊝ Skipping {tool_config.get('name')} (disabled)")
            continue
        
        schema = ToolSchema.from_json_file(str(tool_file))
        self.tools[schema.name] = schema
```

**2. `bin/manage-tools.py`** - New management utility:
- List tools and status
- Enable/disable individual tools
- Bulk operations
- Color-coded output

**3. All `skills/*.tool.json`** - Added `enabled: true` field

### No Hardcoded Dependencies

✅ No tool names in code (dynamically discovered)  
✅ No broken imports if tool disabled  
✅ System prompts mention tools as examples only  
✅ Safe to add/remove tools anytime  

## Token Count Impact

### Example Reduction (Ollama qwen3-vl)

**All 17 tools + 2 MCP servers:**
- Baseline tokens: ~6,200
- With system prompt: ~7,500

**Essential 10 tools only:**
- Baseline tokens: ~3,800 (-39%)
- With system prompt: ~5,100 (-32%)

**Impact:**
- Faster responses (less context to process)
- More room for conversation history
- Less likely to hit context limit

## Best Practices

### 1. Start with Everything Enabled

Get familiar with all tools first:
```bash
./bin/manage-tools.py enable-all
```

### 2. Profile Your Usage

Track which tools you actually use:
```bash
# Check tool usage logs
cat logs/tools/tool-calls-*.jsonl | jq -r '.tool_name' | sort | uniq -c | sort -nr
```

### 3. Disable Rarely Used Tools

```bash
# If you never use crypto prices
./bin/manage-tools.py disable crypto_price

# If you don't use webhooks
./bin/manage-tools.py disable send_webhook
```

### 4. Keep Core Tools Enabled

Always keep these enabled for basic functionality:
- `get_time` - Time/date queries
- `remember` / `recall` / `search_memory` - Memory system
- `get_recent_conversations` - Context awareness

### 5. Document Your Profile

```bash
# Save your enabled tools
./bin/manage-tools.py list > ~/jarvis-voice/skills/profiles/jarvis-tools-profile.txt
```

## Migration (Already Done)

All existing tools have been migrated automatically:

```bash
./bin/manage-tools.py init  # Adds 'enabled': true to all tools
```

Output:
```
✓ Added 'enabled' field to semantic_recall
✓ Added 'enabled' field to search_memory
...
✓ Updated 17 tool(s)
```

## Comparison with MCP Servers

### MCP Servers (`config/mcp-servers.json`)
```json
{
  "mcpServers": {
    "duckduckgo": {
      "command": "docker",
      "enabled": true
    }
  }
}
```

### Local Tools (`skills/*.tool.json`)
```json
{
  "enabled": true,
  "name": "crypto_price",
  "script": "crypto_price.py"
}
```

**Same pattern, consistent experience!**

## Troubleshooting

### Tool Not Loading

```bash
# Check if it's disabled
./bin/manage-tools.py list | grep my_tool

# Enable it
./bin/manage-tools.py enable my_tool
```

### "Tool not found" Error

```bash
# List available tools
./bin/manage-tools.py list

# Check tool file exists
ls -la skills/my_tool.tool.json
```

### Performance Issues with Local Models

```bash
# Check baseline token count
cat logs/baseline-tokens-local.json

# Disable heavy tools
./bin/manage-tools.py disable opencode     # -500 tokens
./bin/manage-tools.py disable execute_bash # -200 tokens
./bin/manage-tools.py disable api_call     # -300 tokens
```

## Future Enhancements

### Profiles (Not Yet Implemented)

```bash
# Save current state as profile
./bin/manage-tools.py save-profile coding

# Load profile
./bin/manage-tools.py load-profile coding
```

### Auto-Detection (Not Yet Implemented)

Automatically disable unused tools after 7 days:
```bash
./bin/manage-tools.py auto-disable --unused-days 7
```

## Summary

✅ **Implemented:**
- Enable/disable field in tool.json
- Tool discovery respects enabled flag
- Management utility (`manage-tools.py`)
- Documentation updated
- All tools migrated

✅ **No Breaking Changes:**
- Backward compatible (defaults to true)
- No hardcoded tool dependencies
- Safe to enable/disable anytime

✅ **Benefits:**
- 30-50% token reduction possible
- Faster responses
- Easier testing
- Better organized tool library

## See Also

- `docs/TOOL_CALLING_SYSTEM.md` - Tool system overview
- `skills/README.md` - Creating custom tools
- `config/mcp-servers.json` - MCP server configuration

