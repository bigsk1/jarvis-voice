# Skills / Tools

This directory contains 50+ executable tools that Jarvis can invoke. Each tool is a Python script paired with a JSON definition file.

---

## Directory Structure

```
skills/
├── *.py              # Tool scripts (executable)
├── *.tool.json       # Tool definitions (schema, permissions)
├── auto-tools/       # Tools created by Tool Builder
│   ├── *.py
│   ├── *.tool.json
│   └── *.report.json # Build audit reports
└── profiles/         # Tool profile overlays (default.json + profiles/examples/ tracked in git)
```

### Tool profiles (optional)

Each profile is `skills/profiles/<name>.json` with `{"description": "...", "overrides": {"tool_name": false}}`. Keys in `overrides` win over the `enabled` flag in `*.tool.json`. Omit a tool to leave the file’s setting unchanged.

Set **`JARVIS_TOOL_PROFILE`** in `config/local.env` or `config/cloud.env` to the profile **name** (stem of the file under `skills/profiles/`, default: `default`). Custom profile JSON files in `skills/profiles/` are gitignored except **`default.json`** and **`docker.json`**. **Copy-paste templates** live in **`skills/profiles/examples/`** (tracked); copy one to `skills/profiles/<name>.json` and set `JARVIS_TOOL_PROFILE=<name>`. For Docker, see the tracked **`docker.json`** profile and [docs/docker/README.md](../docs/docker/README.md).

After changing profile: restart Jarvis services, then run `./bin/sync-tools.py local` or `./bin/sync-tools.py cloud`. Inspect: `./bin/manage-tools.py profile show`.

Example profile you can copy to `skills/profiles/<your_name>.json` and edit (file is gitignored except `default.json`):

```json
{
  "description": "Short note for yourself (optional).",
  "overrides": {
    "weather": false,
    "serpapi_search": false,
    "mcp_fetch_fetch": false,
    "mcp_brave_search_brave_web_search": false
  }
}
```

- Only tools listed under `overrides` are changed; every other tool still follows its `*.tool.json` `enabled` flag.
- If a tool is already **`"enabled": false`** in its `*.tool.json`, you do not need to repeat **`"tool_name": false`** in a profile for the same effect (unless you like documenting intent).
- Overrides may include **names that are not registered** (missing MCP server, typo, removed skill); they are **harmless** and do not raise—only registered tools read those entries.
- Use `true` to force-enable a tool that is disabled in the tool file (uncommon).
- Discover exact tool names (including `mcp_*`): `./bin/manage-tools.py list` or `./bin/manage-tools.py profile export` while the tools you care about are registered.

**Known gap:** profiles control which tools the router can *call*, but meta Q&A (“what can you do?”) may still describe disabled capabilities from the static system prompt or injected intel. That is expected today; see [Runtime-Aware Capability Narration (Q&A)](../docs/ADVANCED_AI_TECHNIQUES.md#design-note-runtime-aware-capability-narration-qa) in `docs/ADVANCED_AI_TECHNIQUES.md` for the problem statement and a possible future enhancement.

CLI reference: `./bin/manage-tools.py -h` and the usage block at the top of `bin/manage-tools.py`.

---

## Tool Discovery

Tools are automatically discovered when they have:
1. A Python script: `toolname.py`
2. A JSON definition: `toolname.tool.json`
3. Executable permission: `chmod +x toolname.py`

The orchestrator loads tools from both `skills/` and `skills/auto-tools/`.

---

## Tool Definition Format

Every tool needs a `.tool.json` file:

```json
{
  "enabled": true,
  "name": "weather",
  "description": "Get current weather and forecast for a location",
  "script": "weather.py",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": "City name or location"
      }
    },
    "required": ["location"]
  },
  "permissions": {
    "dangerous": false,
    "network": true,
    "filesystem": false,
    "bash": false,
    "auto_approve": true
  }
}
```

### Schema Rules For Reliable Tool Calling

For best cross-provider compatibility, keep the top-level `parameters` schema simple:
- `"type": "object"`
- `"properties": { ... }`
- optional `"required": [...]`
- optional `"additionalProperties": false`

Do **not** rely on these at the top level of `parameters`:
- `allOf`
- `anyOf`
- `oneOf`
- `not`
- `if` / `then` / `else`
- `dependentSchemas`
- top-level `enum`

Why:
- OpenAI tool calling is stricter than full JSON Schema and can reject the entire request if one tool has unsupported top-level schema constructs.
- Anthropic may accept more, but the safest shared subset is still plain object + properties.
- Jarvis now sanitizes some unsupported OpenAI schema keywords before sending tools, but new tools should still be authored in the strict subset first.

If you need conditional validation, do it in the tool script itself:
- accept the input schema at the tool-calling layer
- validate combinations like “`group_ids` required when `action=apply`” inside Python
- return a structured error message if inputs are invalid

---

## Tool Contract

### Input
JSON object passed as command line argument:
```bash
./weather.py '{"location": "Portland, OR"}'
```

### Output
JSON object printed to stdout:
```json
{
  "ok": true,
  "speech": "It's 72 degrees and sunny in Portland",
  "data": {
    "temp": 72,
    "condition": "sunny",
    "location": "Portland, OR"
  }
}
```

### Exit Code
- `0`: Success
- Non-zero: Error (with error message in output)

---

## Available Tools (50+)

### Memory
| Tool | Description |
|------|-------------|
| `remember` | Store facts, preferences, technical info |
| `recall` | Retrieve specific memories by category/key |
| `search_memory` | FTS5 full-text keyword search |
| `semantic_recall` | AI-powered conceptual search |
| `update_memory` | Modify existing memories |
| `forget` | Delete memories |
| `deep_memory_search` | Multi-source search (memory, canvas, stash, intel) |

### Conversations
| Tool | Description |
|------|-------------|
| `get_recent_conversations` | Access conversation history |
| `search_conversations` | Search past interactions |

### Media & Content
| Tool | Description |
|------|-------------|
| `generate_image` | AI image generation (Gemini) |
| `analyze_image` | Vision analysis (Grok/Claude/GPT-4o) |
| `generate_music` | AI music creation (ElevenLabs) |
| `pdf_create` | Generate PDFs from content |
| `pdf_read` | Extract text/images from PDFs |
| `screenshot_url` | Full-page screenshots with AI analysis |
| `crawl_url` | Web scraping with Crawl4AI |

### Storage & Output
| Tool | Description |
|------|-------------|
| `stash` | Artifact storage (temp files, 7-day TTL) |
| `canvas` | Visual knowledge pages |
| `printer` | Print from stash/files (CUPS) |

### Communication
| Tool | Description |
|------|-------------|
| `send_email` | Email with HTML templates |
| `send_webhook` | Trigger webhooks (Slack, Discord, APIs) |
| `phone_call` | AI phone calls (Vapi.ai) |

### System & Network
| Tool | Description |
|------|-------------|
| `execute_bash` | Run shell commands |
| `ssh_remote` | SSH into remote hosts |
| `docker_control` | Docker/compose management |
| `network_tools` | Ping, DNS, port checks, traceroute |
| `system_monitor` | CPU, RAM, disk, processes |
| `speaker_volume` | Audio volume control |

### Integrations
| Tool | Description |
|------|-------------|
| `weather` | Weather forecasts (OpenWeatherMap) |
| `crypto_price` | Cryptocurrency prices |
| `stock_price` | Stock/futures/forex prices |
| `serpapi_search` | Generic SerpApi search (Amazon + other engines) |
| `serpapi_home_depot` | SerpApi Home Depot product search with store/ZIP filters |
| `serpapi_maps_search` | SerpApi Google Maps place and local business search |
| `serpapi_hotel_search` | SerpApi Google Hotels search with stay filters |
| `serpapi_youtube` | SerpApi YouTube video details and transcript fallback |
| `serpapi_youtube_search` | SerpApi YouTube video search by keywords |
| `serpapi_yelp_search` | SerpApi Yelp place search with attrs and reviews |
| `spotify` | Music playback control |
| `opencode` | Autonomous coding agent |
| `calculator` | Math, stats, unit conversions |

### Proactive System
| Tool | Description |
|------|-------------|
| `create_reminder` | Time-based reminders |
| `list_reminders` | View scheduled reminders |
| `acknowledge_reminders` | Clear reminders |
| `list_alerts` | View active alerts |
| `acknowledge_alerts` | Dismiss alerts |

### Development
| Tool | Description |
|------|-------------|
| `tool_search` | Discover enabled tools by summary first, then follow exact tool names |
| `check_tool_logs` | View tool/workflow execution logs |
| `check_opencode_sessions` | Monitor OpenCode progress |
| `query_service_logs` | Check background service status |
| `ingest_intel` | Bulk import knowledge files |
| `manage_intel` | Create/manage intel files |

---

## Auto-Tools (Tool Builder)

The `auto-tools/` directory contains tools created by the Dynamic Tool Builder:

| Tool | Description |
|------|-------------|
| `docker_control` | Docker container and compose management |
| `network_tools` | Network diagnostics suite |
| `system_monitor` | System resource monitoring |
| `text_summarizer` | Text processing and analysis |
| `youtube_transcript` | Download YouTube transcripts |
| `status_recap` | Daily status aggregator |
| `generate_password` | Secure password generation |

Each auto-tool includes a `.report.json` with build audit information.

---

## Managing Tools

### Enable/Disable Tools
```bash
# List all tools
./bin/manage-tools.py list

# Disable a tool
./bin/manage-tools.py disable crypto_price

# Enable a tool
./bin/manage-tools.py enable crypto_price
```

### Sync Tools to LLM Context
```bash
# Sync for cloud mode
./bin/sync-tools.py cloud

# Sync for local mode
./bin/sync-tools.py local
```

---

## Creating New Tools

### 1. Use Tool Builder (Recommended)
```bash
./bin/build-tool --mode cloud build "Check if a URL is accessible"
```

### 2. Manual Creation

**Create the script (`skills/mytool.py`):**
```python
#!/usr/bin/env python3
import sys
import json

def main():
    # Parse input from command line
    input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    param = input_data.get("param", "default")
    
    # Do work...
    result = f"Processed: {param}"
    
    # Return JSON
    print(json.dumps({
        "ok": True,
        "speech": result,
        "data": {"param": param}
    }))

if __name__ == "__main__":
    main()
```

**Create the definition (`skills/mytool.tool.json`):**
```json
{
  "enabled": true,
  "name": "mytool",
  "description": "What the tool does - be specific for Tool RAG",
  "script": "mytool.py",
  "parameters": {
    "type": "object",
    "properties": {
      "param": {
        "type": "string",
        "description": "Parameter description"
      }
    },
    "required": ["param"]
  },
  "permissions": {
    "dangerous": false,
    "network": false,
    "filesystem": false,
    "bash": false,
    "auto_approve": true
  }
}
```

**Make executable and sync:**
```bash
chmod +x skills/mytool.py
./bin/sync-tools.py cloud
```

## Note 
If you add a new tool and want to be able to follow up on the result, you need to add it to the `FOLLOWUP_FIELDS` dict in `jarvis-web/server/sockets/chat.py` → `_extract_followup_data()`.

Print statements must have in tool *.py files file=sys.stderr so they are not printed to the console.

---

## Testing Tools

```bash
# Direct execution
./skills/weather.py '{"location": "Seattle"}'

# Via orchestrator
./orchestrator/orchestrator_v2.py cloud "What's the weather in Seattle?"

# Check tool logs
./orchestrator/orchestrator_v2.py cloud "show recent tool logs"
```

---

## Tool RAG Integration

Tools are discovered dynamically using semantic search:
- Only relevant tools are loaded per query (reduces context)
- Tool descriptions are embedded for similarity matching
- "Ghost tools" (critical tools) are always available

---

## Related Documentation

- **[TOOL_CALLING_SYSTEM.md](../docs/TOOL_CALLING_SYSTEM.md)** - How tool routing works
- **[TOOL_MANAGEMENT.md](../docs/TOOL_MANAGEMENT.md)** - Enable/disable tools
- **[TOOL_RAG_STRATEGY.md](../docs/TOOL_RAG_STRATEGY.md)** - Dynamic tool discovery
- **[TOOL_BUILDER.md](../docs/TOOL_BUILDER.md)** - Automatic tool creation
- **[STASH_SYSTEM.md](../docs/STASH_SYSTEM.md)** - Artifact storage for tools
