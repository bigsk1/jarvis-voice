# Jarvis Tool Calling System

## Overview

Your Jarvis voice assistant can now **execute real-world tasks** through natural language commands! The system uses native tool calling from Anthropic Claude, OpenAI, or Ollama to intelligently route commands and execute tools.

## Quick Start

### 1. Setup (One-time)

```bash
cd ~/jarvis-voice
chmod +x setup_tools.sh
./setup_tools.sh
```

### 2. Configure API Key

Edit `config/cloud.env`:
```bash
# Use Anthropic Claude (recommended)
LLM_PROVIDER="anthropic"
ANTHROPIC_API_KEY="sk-ant-your-key-here"

# Or use OpenAI
LLM_PROVIDER="openai"
OPENAI_API_KEY="sk-your-key-here"
```

# Or use xAI Grok
LLM_PROVIDER="xai"
XAI_API_KEY="xai-your-key-here"
XAI_MODEL="grok-4.3"

### 3. Test It

```bash
# Test a tool directly
echo '{}' | ./skills/time.sh

# Test via orchestrator
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Test with voice
jarvis
> "Hey Jarvis"
> "What time is it?"
```

## What Can It Do?

### Built-in Tools

| Tool | Command Examples | Permission Level |
|------|-----------------|------------------|
| **get_time** | "What time is it?", "Tell me the date" | ✅ Auto-approved |
| **tool_search** | "Find the tool that can inspect logs", "Browse available tools" | ✅ Auto-approved |
| **send_webhook** | "Send webhook to URL with data X" | ⚠️ Network |
| **api_call** | "Call the API at github.com/users/X" | ⚠️ Network |
| **execute_bash** | "Run the command uptime" | 🚨 Dangerous |

`tool_search` is a summary-first discovery tool. In semantic and browse mode it focuses on non-ghost tools, because ghost tools are already visible every routing turn. Exact lookup can still inspect a ghost tool by name when needed.

### Example Commands

**Safe operations:**
- "What time is it?"
- "What's today's date?"

**Network operations:**
- "Send a webhook to https://httpbin.org/post with message hello world"
- "Call the API at https://api.github.com/zen with GET method"
- "Send a POST request to my webhook URL with status running"

**Conversational (no tool):**
- "How are you doing?"
- "Tell me about quantum computing"
- "What's the capital of France?"

**System operations:**
- "Run the command df -h"
- "Execute uptime"
- "Show me disk usage"

## How It Works

```
You say: "Send a webhook to my server with status online"
            ↓
Wake Word Detection (openwakeword)
            ↓
Speech-to-Text (OpenAI Whisper / faster-whisper)
            ↓
LLM Provider (xAI/Claude/GPT/Ollama)
  • Understands intent: send_webhook tool
  • Extracts parameters: {url: "...", data: {...}}
            ↓
Permission Check
  • Network access required → Announces action
            ↓
Tool Execution (send_webhook.py)
  • Makes HTTP POST request
  • Returns: {"ok": true, "speech": "Webhook sent successfully"}
            ↓
Text-to-Speech (OpenAI TTS / Kokoro)
            ↓
You hear: "Webhook sent successfully to your server. Status 200."
```

Tool availability is selected just before the router LLM call by Tool RAG. Local mode retrieves top 5 semantic tools and cloud mode retrieves top 15, then ghost tools and exact positive tool signals are merged in. `tool_search` is also always available as a mandatory ghost tool, so the model can discover enabled tools when the current shortlist is not enough. For live debugging of which tools were made available, enable `TOOL_RAG_TRACE_ENABLED=true` and inspect `logs/tool-rag/tool-rag-YYYY-MM-DD.jsonl`; see `docs/TOOL_RAG_STRATEGY.md`.

## Provider Comparison

| Provider | Tool Calling | Speed | Cost | Privacy |
|----------|-------------|-------|------|---------|
| **Anthropic Claude** | ✅ Native | Fast | Medium | Cloud |
| **OpenAI GPT** | ✅ Native | Fast | Low | Cloud |
| **Ollama (local model)** | ⚠️ Structured prompts | Model-dependent | Free | Local |
| **Ollama Cloud** | ⚠️ Structured prompts | Network-dependent | Subscription/unknown | Cloud via signed-in daemon |
| **xAI Grok 4.3** | ✅ Native | Medium | Low | Cloud |

**Recommendation:** Use xAI Grok 4.3 for agentic tool calling accuracy.

## Creating Custom Tools

### 1. Create Tool Script

Example file `skills/my_automation.py` (create it first):
```python
#!/usr/bin/env python3
import sys, json, requests

# Read input
input_data = json.load(sys.stdin)
action = input_data.get("action")

# Execute your automation
result = requests.post("https://your-api.com/action", json={"action": action})

# Return result
print(json.dumps({
    "ok": True,
    "speech": f"Completed {action} successfully",
    "data": {"status": "done"}
}))
```

### 2. Create Tool Schema

`skills/my_automation.tool.json`:
```json
{
  "enabled": true,
  "name": "my_automation",
  "description": "Trigger home automation actions",
  "script": "my_automation.py",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "description": "The action to perform (lights_on, lock_door, etc.)"
      }
    },
    "required": ["action"]
  },
  "permissions": {
    "network": true,
    "auto_approve": false
  }
}
```

### Tool Schema Compatibility Notes

Jarvis tool schemas are provider-agnostic in storage, but cloud providers do not all accept the same JSON Schema surface area for function/tool calling.

Safest cross-provider rule:
- Top-level `parameters` should always be a plain object schema:
  - `"type": "object"`
  - `"properties": { ... }`
  - optional `"required": [...]`
  - optional `"additionalProperties": false`

Avoid these at the **top level** of `parameters` if you want the schema to work reliably with OpenAI tool calling:
- `allOf`
- `anyOf`
- `oneOf`
- `not`
- `if` / `then` / `else`
- `dependentSchemas`
- top-level `enum`

Example of the recommended shape:

```json
{
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "location": {
        "type": "string",
        "description": "City name or location"
      },
      "units": {
        "type": "string",
        "enum": ["imperial", "metric"],
        "description": "Temperature units"
      }
    },
    "required": ["location"]
  }
}
```

Notes:
- Nested schema features may still work with some providers, but the safest authoring target is the common subset above.
- OpenAI is currently the strictest path in this repo for tool schema validation.
- Anthropic is generally more tolerant of richer `input_schema`, but if you want one schema that works across OpenAI, Anthropic, xAI/OpenAI-compatible paths, and Ollama prompts, stick to the object/properties/required subset.
- Jarvis now sanitizes some unsupported keywords before sending tools to OpenAI, but that is a compatibility fallback, not a license to author overly-complex schemas.

### 3. Make Executable & Use

```bash
chmod +x skills/my_automation.py

# Test
echo '{"action":"lights_on"}' | ./skills/my_automation.py

# Use with voice
jarvis
> "Hey Jarvis"
> "Turn on the lights"  ← LLM automatically calls my_automation tool
```

### New Tool Checklist

When adding a new tool, don't forget these steps beyond the script + schema:

1. **Follow-up extraction** — If your tool produces artifacts (files, stash refs), entity IDs
   (memory_id, reminder_id, page_id), or session state (host, container, URL) that a user
   might reference in follow-up questions, add it to the `FOLLOWUP_FIELDS` dict in
   `jarvis-web/server/services/followup_extractor.py`.

   This is what lets the LLM act on previous results across separate API calls (e.g.,
   "email that PDF" after a `pdf_create`, or "cancel that reminder" after `create_reminder`).

   Only extract identifiers and references — not content. The LLM already sees the speech text.

   ```python
   # In followup_extractor.py:
   'my_new_tool': ['some_id', 'stash_ref', 'relevant_field'],
   ```

   Dedicated extraction branches also live in `followup_extractor.py` for tools with nested
   or non-standard output shapes, such as `crawl_url` and MCP Brave search results. The
   `ChatHandler` methods in `jarvis-web/server/sockets/chat.py` are compatibility delegates.

2. **Memory entry** — If the tool creates a stash artifact, save a memory entry pointing
   to it (see `generate_image.py` for the pattern). This enables cross-session discovery.

3. **Stash integration** — If the tool produces files, save to stash and return a
   `stash_ref` or `ref`. See `docs/STASH_SYSTEM.md` for the `ref` vs `stash_ref` naming.

4. **Schema discipline** — Keep the top-level `parameters` schema in the strict subset above.
   If you need conditional validation, enforce it inside the tool code and return a clear
   runtime error instead of relying on top-level JSON Schema combinators.

---

## Managing Tools (Enable/Disable)

Control which tools are loaded to reduce token count and improve performance:

```bash
# List all tools and their status
./bin/manage-tools.py list

# List with descriptions
./bin/manage-tools.py list -v

# Disable a tool (reduces token count)
./bin/manage-tools.py disable execute_bash

# Enable a tool
./bin/manage-tools.py enable execute_bash

# Enable all tools
./bin/manage-tools.py enable-all
```

**Why disable tools?**
- Reduce baseline token count (important for local models)
- Faster responses (less context for LLM to process)
- Create focused "profiles" (e.g., coding tools only, home automation only)
- Easier testing and debugging

**Example: Disable test/sample tools:**
```bash
./bin/manage-tools.py disable send_webhook
./bin/manage-tools.py disable api_call
```

**Note:** Disabled tools are skipped at startup - no performance impact!

## Permission System

Tool permissions are defined in the tool schema file and not fully implemented yet. FUTURE TODO:

```json
{
  "permissions": {
    "dangerous": false,     // Extra caution (rm, dd, etc.)
    "bash": false,         // Executes shell commands
    "network": true,       // Makes HTTP requests
    "filesystem": false,   // Reads/writes files
    "auto_approve": false  // Skip announcement
  }
}
```

**Levels:**
- ✅ **Auto-approved** (`auto_approve: true`) - Safe tools, executes silently
- ⚠️ **Announced** (`network/filesystem/bash`) - Announces before executing
- 🚨 **Dangerous** (`dangerous: true`) - Shows warning + announces

## Architecture Files

```
lib/
  tool_schema.py       - Universal tool schemas
  llm_provider.py      - Provider abstraction (Anthropic/OpenAI/Ollama)

orchestrator/
  router_v2.py         - LLM-based intelligent routing
  executor.py          - Tool execution with permissions
  orchestrator_v2.py   - Main coordinator

skills/
  *.tool.json          - Tool schemas
  *.py / *.sh          - Tool implementations

bin/
  wake-jarvis.py               - Wake word loop (cloud)
  wake-jarvis-local.py         - Wake word loop (local)
  question-orchestrator.sh     - Q&A with tools (cloud)
  question-orchestrator-local.sh - Q&A with tools (local)
```

## Switching Providers

### To xAI Grok 4.3 (Recommended)

`config/cloud.env`:
```bash
LLM_PROVIDER="xai"
XAI_API_KEY="xai-..."
XAI_MODEL="grok-4.3"
```

### To Anthropic Claude

`config/cloud.env`:
```bash
LLM_PROVIDER="anthropic"
ANTHROPIC_API_KEY="sk-..."
ANTHROPIC_MODEL="claude-sonnet-4-20250514"
```

### To OpenAI

`config/cloud.env`:
```bash
LLM_PROVIDER="openai"
OPENAI_API_KEY="sk-..."
OPENAI_MODEL="gpt-4o-mini"
```

### To Ollama (Local)

`config/local.env`:
```bash
LLM_PROVIDER="ollama"
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_MODEL="llama3.1:latest"
```

Then use `jarvis-local` instead of `jarvis`.

### To Ollama Cloud

`config/cloud.env`:

```bash
LLM_PROVIDER="ollama"
OLLAMA_BASE_URL="http://your-signed-in-ollama-host:11434"
OLLAMA_CLOUD_MODEL="minimax-m3:cloud"
```

Use normal cloud startup (`./jarvis`). Jarvis requires a recognized `*:cloud`
or `*-cloud` model tag in cloud mode and does not append localhost to the cloud
host list. See [ollama/README.md](ollama/README.md).

## Troubleshooting

**"Tool not found"**
- Ensure `.tool.json` exists in `skills/`
- Run `./setup_tools.sh` to verify registration

**"API key invalid"**
- Check `config/cloud.env` for correct API key
- Ensure no quotes or extra spaces

**"Permission denied"**
- Run `chmod +x skills/*.py`
- Or run `./setup_tools.sh`

**"Module not found: anthropic"**
- Run `pip install anthropic openai`
- Or run `./setup_tools.sh`

## Documentation

- 📖 **TOOL_SYSTEM_SUMMARY.md** - Complete architecture overview
- 📖 **TESTING.md** - Comprehensive testing guide
- 📖 **orchestrator/README.md** - Orchestrator details
- 📖 **skills/README.md** - Tool creation guide

## Inter-Tool Calling (Tools Calling Other Tools)

Some tools need to call other tools internally. For example:
- `stash.remember` calls `pdf_read` to extract text from PDFs
- `status_recap` calls `weather`, `crypto_price`, `stock_price`, etc.

### Pattern: Subprocess Tool Calls

```python
import subprocess
import json
import os

# Tool locations
SKILLS_DIR = os.path.dirname(__file__)
AUTO_TOOLS_DIR = os.path.join(SKILLS_DIR, 'auto-tools')

def find_tool(tool_name: str) -> str:
    """Find tool path - check skills/ then skills/auto-tools/"""
    tool_path = os.path.join(SKILLS_DIR, f"{tool_name}.py")
    if os.path.exists(tool_path):
        return os.path.abspath(tool_path)
    tool_path = os.path.join(AUTO_TOOLS_DIR, f"{tool_name}.py")
    if os.path.exists(tool_path):
        return os.path.abspath(tool_path)
    return None

def call_tool(tool_name: str, args: dict = None, timeout: int = 60) -> dict:
    """Call another Jarvis tool and return its result."""
    try:
        tool_path = find_tool(tool_name)
        if not tool_path:
            return {"ok": False, "error": f"Tool {tool_name} not found"}

        # Get project root for proper module resolution
        project_root = os.path.join(os.path.dirname(__file__), '..')

        input_data = json.dumps(args or {})
        cmd = ["python3", tool_path, input_data]

        # Run from project root so tools can find their lib imports
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_root
        )

        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
        return {"ok": False, "error": result.stderr or f"Tool {tool_name} failed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{tool_name} timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

### Usage Example

```python
# In stash.py - call pdf_read to extract text from PDFs
def extract_pdf_text(file_path: str) -> str:
    result = call_tool('pdf_read', {
        'action': 'extract_text',
        'file_path': file_path
    })

    if result.get('ok') and result.get('data', {}).get('text'):
        return result['data']['text']
    return None
```

### Key Points

1. **Search both directories**: Tools can be in `skills/` or `skills/auto-tools/`
2. **Run from project root**: Use `cwd=project_root` so tools can import from `lib/`
3. **Pass args as JSON**: Tools expect `sys.argv[1]` to be a JSON string
4. **Handle timeouts**: Set appropriate timeouts (default 60s, longer for image generation)
5. **Parse JSON response**: All tools return `{"ok": bool, "speech": str, "data": {...}}`

### Tools Using This Pattern

| Tool | Calls | Purpose |
|------|-------|---------|
| `stash.py` | `pdf_read` | Extract text from PDFs for memory storage |
| `status_recap.py` | `weather`, `crypto_price`, `stock_price`, `generate_image`, `canvas`, `stash` | Aggregate status data |
| `deep_memory_search.py` | Uses `ripgrep` subprocess | Search file contents |

---

## What's Next?

1. **Add your tools** - Home automation, webhooks, API integrations
2. **Test voice commands** - Start jarvis and try different commands
3. **Customize permissions** - Adjust auto-approval for your tools
4. **Build workflows** - Chain multiple tools together
5. **Add confirmation loops** - For critical operations

## Support

- Check logs in `audio/cloud/logs/` or `audio/local/logs/`
- Test tools individually: `echo '{}' | ./skills/<tool-name>.py`
- Test orchestrator: `./orchestrator/orchestrator_v2.py cloud "command"`
- Read testing guide: `TESTING.md`

---

**You now have a voice-activated AI that can actually DO things!** 🚀
