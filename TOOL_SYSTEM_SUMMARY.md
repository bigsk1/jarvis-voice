# Tool Calling System - Implementation Summary

## 🎉 What We Built

A **production-ready, provider-agnostic tool calling system** that enables Jarvis to execute real-world tasks through voice commands. You can now ask Jarvis to:

- ✅ Send webhooks to external services
- ✅ Make API calls to REST endpoints  
- ✅ Execute bash commands (with safety checks)
- ✅ Get system information (time, status, etc.)
- ✅ And easily add any custom tool you need

## 🏗️ Architecture

```
Voice Input
    ↓
Wake Word Detection
    ↓
Speech-to-Text (STT)
    ↓
┌─────────────────────────────────┐
│  LLM Provider (You Choose)      │
│  • Anthropic Claude Sonnet 4.5  │ ← Your preference
│  • OpenAI GPT-4                 │
│  • Ollama (Local)               │
└─────────────────────────────────┘
    ↓
Tool Calling (Native Function Calling)
    ↓
┌─────────────────────────────────┐
│  Router (Intelligent)           │
│  • Determines: Tool or Q&A      │
│  • Extracts parameters          │
│  • Validates input              │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  Executor (Permission-Aware)    │
│  • Checks permissions           │
│  • Announces dangerous actions  │
│  • Executes tool safely         │
└─────────────────────────────────┘
    ↓
Confirmation & Response
    ↓
Text-to-Speech (TTS)
    ↓
Audio Output
```

## 📦 Components

### 1. **lib/tool_schema.py** - Universal Tool Registry
- Tool discovery system (finds `*.tool.json` files)
- Converts tool schemas for different LLM providers
- Manages permissions (bash, network, filesystem, dangerous)
- Auto-approval system for safe tools

### 2. **lib/llm_provider.py** - Provider Abstraction
- **AnthropicProvider** - Native tool calling with Claude
- **OpenAIProvider** - Function calling with GPT models
- **OllamaProvider** - Structured prompting for local models
- Unified interface: `chat_with_tools()`

### 3. **orchestrator/router_v2.py** - Intelligent Router
- Uses LLM to understand intent
- Routes to appropriate handler (tool vs Q&A)
- Extracts parameters automatically
- No hardcoded keywords needed!

### 4. **orchestrator/executor.py** - Safe Executor (Enhanced)
- Permission checking before execution
- Timeout protection (10s default)
- Error handling and reporting
- JSON I/O with tools

### 5. **orchestrator/orchestrator_v2.py** - Main Coordinator
- Combines routing + execution
- Formats responses for TTS
- Handles errors gracefully
- Returns structured results

### 6. **bin/question-orchestrator.sh** - Integration Script
- Records audio → STT → Orchestrator → TTS
- Saves transcripts and audio files
- Handles cloud mode

### 7. **bin/question-orchestrator-local.sh** - Local Version
- Same flow, uses local STT/TTS/LLM
- Works fully offline

## 🛠️ Tools Included

### get_time (Safe)
- **Permission:** Auto-approved
- **Usage:** "What time is it?"
- **Does:** Returns current date/time

### send_webhook (Network)
- **Permission:** Network access
- **Usage:** "Send a webhook to URL with data X"
- **Does:** POST request to any webhook

### api_call (Network)
- **Permission:** Network access
- **Usage:** "Call the API at URL"
- **Does:** GET/POST/PUT/DELETE to REST APIs

### execute_bash (Dangerous)
- **Permission:** Bash + Filesystem + Dangerous
- **Usage:** "Run the command uptime"
- **Does:** Executes bash commands with safety blocks

## 🔐 Permission System

Every tool declares its permissions in `.tool.json`:

```json
{
  "permissions": {
    "dangerous": false,     // Extra caution required
    "bash": false,         // Executes shell commands
    "network": true,       // Makes HTTP requests
    "filesystem": false,   // Reads/writes files
    "auto_approve": false  // Requires announcement
  }
}
```

**Behavior:**
- `auto_approve: true` → Executes silently (safe tools like time)
- `auto_approve: false` → Announces action before executing
- `dangerous: true` → Shows warning message

## 🚀 How to Use

### Quick Start

1. **Install dependencies:**
```bash
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate
pip install anthropic openai
```

2. **Configure your API key** in `config/cloud.env`:
```bash
ANTHROPIC_API_KEY="your-key-here"
LLM_PROVIDER="anthropic"  # or "openai" or "ollama"
```

3. **Make scripts executable:**
```bash
chmod +x skills/*.py
chmod +x bin/question-orchestrator*.sh
```

4. **Start Jarvis:**
```bash
jarvis  # Cloud mode with tool calling enabled
```

5. **Try it:**
- "Hey Jarvis"
- "What time is it?" ← Executes get_time tool
- "Send a webhook to https://httpbin.org/post with message hello"

### Configuration Options

**Cloud Mode (`config/cloud.env`):**
```bash
# Choose your LLM provider
LLM_PROVIDER="anthropic"        # Recommended for tool calling

# Anthropic Claude (powerful, reliable)
ANTHROPIC_API_KEY="sk-ant-..."
ANTHROPIC_MODEL="claude-sonnet-4-20250514"

# OpenAI (alternative)
LLM_PROVIDER="openai"
OPENAI_API_KEY="sk-..."
CHAT_MODEL="gpt-4o-mini"
```

**Local Mode (`config/local.env`):**
```bash
LLM_PROVIDER="ollama"
OLLAMA_BASE_URL="http://192.168.70.226:11434"
OLLAMA_MODEL="Godmoded/llama3-lexi-uncensored:latest"
```

## 📝 Creating Your Own Tools

### Example: Home Automation Tool

**1. Create `skills/lights_on.tool.json`:**
```json
{
  "name": "lights_on",
  "description": "Turn on smart lights in a specified room",
  "script": "lights_on.py",
  "parameters": {
    "type": "object",
    "properties": {
      "room": {
        "type": "string",
        "description": "The room name (living room, bedroom, kitchen)"
      },
      "brightness": {
        "type": "integer",
        "description": "Brightness level 0-100"
      }
    },
    "required": ["room"]
  },
  "permissions": {
    "dangerous": false,
    "bash": false,
    "network": true,
    "filesystem": false,
    "auto_approve": false
  }
}
```

**2. Create `skills/lights_on.py`:**
```python
#!/usr/bin/env python3
import sys, json, requests

input_data = json.load(sys.stdin)
room = input_data.get("room")
brightness = input_data.get("brightness", 100)

# Call your smart home API
response = requests.post(
    "https://your-home-api.com/lights",
    json={"room": room, "on": True, "brightness": brightness}
)

if response.status_code == 200:
    result = {
        "ok": True,
        "speech": f"Lights turned on in {room} at {brightness} percent brightness",
        "data": {"room": room, "brightness": brightness}
    }
else:
    result = {
        "ok": False,
        "speech": f"Failed to turn on lights in {room}",
        "error": response.text
    }

print(json.dumps(result))
```

**3. Make executable:**
```bash
chmod +x skills/lights_on.py
```

**4. Test:**
```bash
# Direct test
echo '{"room":"living room","brightness":80}' | ./skills/lights_on.py

# Via orchestrator
./orchestrator/orchestrator_v2.py cloud "Turn on the lights in the living room at 80 percent"

# Via voice
jarvis
> "Hey Jarvis"
> "Turn on the lights in the living room"
```

## 🎯 Real-World Use Cases

### 1. Home Automation
- "Turn on the lights in the bedroom"
- "Set thermostat to 72 degrees"
- "Lock the front door"

### 2. Development Workflow
- "Deploy to staging server"
- "Run the test suite"
- "Restart the Docker containers"

### 3. System Administration
- "Check disk space on the server"
- "Show me the system load"
- "Restart nginx"

### 4. API Integration
- "Check my GitHub notifications"
- "Send a message to Slack"
- "Get the weather forecast"

### 5. Data Queries
- "Query the database for user count"
- "Get sales data from yesterday"
- "Show me the latest logs"

## 🔮 Future Enhancements

- [ ] **Verbal confirmation loop** - "Are you sure you want to...?"
- [ ] **Multi-step workflows** - Chain multiple tools
- [ ] **Context awareness** - Remember previous commands
- [ ] **MCP server integration** - Use Model Context Protocol
- [ ] **Tool marketplace** - Share/discover community tools
- [ ] **Async execution** - Long-running tasks in background
- [ ] **Rollback capability** - Undo dangerous operations
- [ ] **Audit logging** - Track all tool executions

## 📚 Key Files Reference

```
jarvis-voice/
├── lib/
│   ├── tool_schema.py          # Tool registry & schemas
│   ├── llm_provider.py         # LLM provider abstraction
│   └── config_loader.py        # Config management
├── orchestrator/
│   ├── router_v2.py            # LLM-based router
│   ├── executor.py             # Tool executor (enhanced)
│   └── orchestrator_v2.py      # Main coordinator
├── skills/
│   ├── get_time.tool.json      # Tool schema
│   ├── time.sh                 # Tool script
│   ├── send_webhook.tool.json  # Webhook schema
│   ├── send_webhook.py         # Webhook script
│   ├── api_call.tool.json      # API schema
│   ├── api_call.py             # API script
│   ├── execute_bash.tool.json  # Bash schema
│   └── execute_bash.py         # Bash script
├── bin/
│   ├── wake_jarvis.py          # Wake word (cloud) - UPDATED
│   ├── wake_jarvis_local.py    # Wake word (local) - UPDATED
│   ├── question-orchestrator.sh       # Q&A with orchestrator (cloud)
│   └── question-orchestrator-local.sh # Q&A with orchestrator (local)
├── config/
│   ├── cloud.env               # Cloud config - UPDATED
│   └── local.env               # Local config - UPDATED
└── TEST_TOOL_SYSTEM.md         # Testing guide
```

## 🎓 Key Concepts

### Provider-Agnostic Design
- Same tool works with any LLM provider
- Switch providers by changing config
- No vendor lock-in

### Permission-Based Security
- Tools declare capabilities
- Auto-approval for safe operations
- Announcements for risky actions

### Natural Language Interface
- No keyword matching needed
- LLM understands intent
- Extracts parameters automatically

### Modular Architecture
- Easy to add new tools
- Easy to add new providers
- Easy to extend functionality

## 🐛 Troubleshooting

See `TEST_TOOL_SYSTEM.md` for detailed troubleshooting steps.

Common issues:
- Missing API keys → Check `config/cloud.env`
- Tool not found → Check `.tool.json` exists
- Permission denied → Run `chmod +x skills/*.py`
- Import errors → Run `pip install anthropic openai`

## 📖 Documentation

- `TEST_TOOL_SYSTEM.md` - Comprehensive testing guide
- `orchestrator/README.md` - Orchestrator architecture
- `skills/README.md` - Tool creation guide

---

**You now have a voice-activated AI assistant that can DO things, not just talk!** 🚀

Next step: Add your specific tools for home automation, webhooks, API integrations, etc.

