# Jarvis Tool Calling System

## Overview

Your Jarvis voice assistant can now **execute real-world tasks** through natural language commands! The system uses native tool calling from Anthropic Claude, OpenAI, or Ollama to intelligently route commands and execute tools.

## Quick Start

### 1. Setup (One-time)

```bash
cd /home/boss/jarvis-voice
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

# Or use xAI Grok-4-fast
LLM_PROVIDER="xai"
XAI_API_KEY="xai-your-key-here"
XAI_MODEL="grok-4-fast-reasoning-latest"

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
| **send_webhook** | "Send webhook to URL with data X" | ⚠️ Network |
| **api_call** | "Call the API at github.com/users/X" | ⚠️ Network |
| **execute_bash** | "Run the command uptime" | 🚨 Dangerous |

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

## Provider Comparison

| Provider | Tool Calling | Speed | Cost | Privacy |
|----------|-------------|-------|------|---------|
| **Anthropic Claude** | ✅ Native | Fast | Medium | Cloud |
| **OpenAI GPT** | ✅ Native | Fast | Low | Cloud |
| **Ollama (Local)** | ⚠️ Structured prompts | Slower | Free | Local |
| **xAI Grok-4-fast** | ✅ Native | Fast | Low | Cloud |

**Recommendation:** Use xAI Grok-4-fast for best tool calling accuracy.

## Creating Custom Tools

### 1. Create Tool Script

`skills/my_automation.py`:
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
  wake_jarvis.py               - Wake word loop (cloud) ✨ UPDATED
  wake_jarvis_local.py         - Wake word loop (local) ✨ UPDATED
  question-orchestrator.sh     - Q&A with tools (cloud)
  question-orchestrator-local.sh - Q&A with tools (local)
```

## Switching Providers

### To xAI Grok-4-fast (Recommended)

`config/cloud.env`:
```bash
LLM_PROVIDER="xai"
XAI_API_KEY="xai-..."
XAI_MODEL="grok-4-fast-reasoning-latest"
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
CHAT_MODEL="gpt-4o-mini"
```

### To Ollama (Local)

`config/local.env`:
```bash
LLM_PROVIDER="ollama"
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_MODEL="llama3.1:latest"
```

Then use `jarvis-local` instead of `jarvis`.

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
- 📖 **TEST_TOOL_SYSTEM.md** - Comprehensive testing guide
- 📖 **orchestrator/README.md** - Orchestrator details
- 📖 **skills/README.md** - Tool creation guide

## What's Next?

1. **Add your tools** - Home automation, webhooks, API integrations
2. **Test voice commands** - Start jarvis and try different commands
3. **Customize permissions** - Adjust auto-approval for your tools
4. **Build workflows** - Chain multiple tools together
5. **Add confirmation loops** - For critical operations

## Support

- Check logs in `audio/cloud/logs/` or `audio/local/logs/`
- Test tools individually: `echo '{}' | ./skills/tool.py`
- Test orchestrator: `./orchestrator/orchestrator_v2.py cloud "command"`
- Read testing guide: `TESTING.md`

---

**You now have a voice-activated AI that can actually DO things!** 🚀

