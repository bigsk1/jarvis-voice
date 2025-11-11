# Testing the Tool Calling System

This guide will help you test the new LLM-based tool calling system with Anthropic Claude, OpenAI, or Ollama.

## Prerequisites

### 1. Install New Dependencies

```bash
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate
pip install anthropic openai
```

### 2. Configure API Keys

Edit `/home/boss/jarvis-voice/config/cloud.env`:

```bash
# Set your Anthropic API key (recommended)
ANTHROPIC_API_KEY="your-key-here"

# Or use OpenAI
LLM_PROVIDER="openai"  # Change to "anthropic" for Claude
```

### 3. Make Scripts Executable

```bash
chmod +x skills/*.py
chmod +x bin/question-orchestrator*.sh
chmod +x orchestrator/*.py
```

## Testing Tools Individually

### Test Tool Registry

```bash
cd /home/boss/jarvis-voice
python3 -c "
from lib.tool_schema import ToolRegistry
registry = ToolRegistry('skills')
print('Available tools:', registry.list_tools())
"
```

**Expected output:**
```
✓ Registered tool: send_webhook
✓ Registered tool: get_time
✓ Registered tool: execute_bash
✓ Registered tool: api_call
Available tools: ['send_webhook', 'get_time', 'execute_bash', 'api_call']
```

### Test Individual Tools

#### Get Time (Safe, Auto-approved)
```bash
echo '{}' | ./skills/time.sh
```

**Expected:** Current time and date in JSON format

#### Send Webhook (Network permission)
```bash
echo '{"url":"https://httpbin.org/post","data":{"message":"test"}}' | ./skills/send_webhook.py
```

**Expected:** Success message with HTTP 200

#### API Call
```bash
echo '{"url":"https://httpbin.org/get","method":"GET"}' | ./skills/api_call.py
```

**Expected:** JSON response from httpbin

#### Execute Bash (Dangerous, requires confirmation)
```bash
echo '{"command":"echo Hello World"}' | ./skills/execute_bash.py
```

**Expected:** "Hello World" output

## Testing the Orchestrator

### Test Router (Intent Detection)

```bash
# Should route to get_time tool
./orchestrator/router_v2.py cloud "What time is it?"

# Should route to Q&A
./orchestrator/router_v2.py cloud "Tell me a joke"

# Should route to api_call tool
./orchestrator/router_v2.py cloud "Call the API at httpbin.org"
```

### Test Full Orchestrator

```bash
# Test with time tool
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Test with conversational Q&A
./orchestrator/orchestrator_v2.py cloud "What is the capital of France?"

# Test with webhook
./orchestrator/orchestrator_v2.py cloud "Send a webhook to https://httpbin.org/post with data hello world"
```

## Testing End-to-End (Without Wake Word)

### Cloud Mode (with Anthropic/OpenAI)

```bash
source ~/jarvis-venv/bin/activate
./bin/question-orchestrator.sh "What time is it?"
```

**Expected flow:**
1. ✅ Transcribes input (or uses provided text)
2. 🧠 Routes through orchestrator
3. 🔧 Executes get_time tool
4. 🗣️ Speaks result via TTS

### Local Mode (with Ollama)

```bash
source ~/jarvis-venv/bin/activate
./bin/question-orchestrator-local.sh "What time is it?"
```

## Testing with Wake Word

### Start Jarvis (Cloud Mode)

```bash
source ~/jarvis-venv/bin/activate
jarvis  # or: ./bin/wake_jarvis.py
```

**Say:** "Hey Jarvis"
**Then say:** "What time is it?"

**Expected:**
- Wake word triggers
- Greeting plays
- Records your question
- Executes get_time tool
- Speaks the current time

### Start Jarvis (Local Mode)

```bash
source ~/jarvis-venv/bin/activate
jarvis-local  # or: ./bin/wake_jarvis_local.py
```

## Example Voice Commands to Test

### Safe Tools (Auto-approved)
- "What time is it?"
- "Tell me the date"

### Network Tools (Announced)
- "Send a webhook to https://httpbin.org/post with data status running"
- "Call the API at https://api.github.com/users/octocat"
- "Get data from https://httpbin.org/get"

### Conversational (No tool)
- "What is the capital of France?"
- "Tell me about quantum computing"
- "How are you doing today?"

### Dangerous Tools (Announced with warning)
- "Run the bash command df -h"
- "Execute the command uptime"

## Troubleshooting

### Tool not found
```
❌ Tool X not found
```
**Fix:** Ensure `X.tool.json` exists in `skills/` directory

### LLM provider error
```
❌ OpenAI API error: Invalid API key
```
**Fix:** Check API keys in `config/cloud.env`

### Permission denied
```
❌ Permission denied: ./skills/tool.py
```
**Fix:** `chmod +x skills/*.py`

### Import errors
```
ModuleNotFoundError: No module named 'anthropic'
```
**Fix:** `pip install anthropic openai`

## Creating Your Own Tools

### 1. Create Tool Script

`skills/my_tool.py`:
```python
#!/usr/bin/env python3
import sys, json

input_data = json.load(sys.stdin)
param = input_data.get("param", "default")

# Do your work here...

result = {
    "ok": True,
    "speech": f"Task completed with {param}",
    "data": {"result": "success"}
}
print(json.dumps(result))
```

### 2. Create Tool Schema

`skills/my_tool.tool.json`:
```json
{
  "name": "my_tool",
  "description": "What this tool does",
  "script": "my_tool.py",
  "parameters": {
    "type": "object",
    "properties": {
      "param": {
        "type": "string",
        "description": "Description of parameter"
      }
    },
    "required": ["param"]
  },
  "permissions": {
    "dangerous": false,
    "bash": false,
    "network": false,
    "filesystem": false,
    "auto_approve": true
  }
}
```

### 3. Make Executable & Test

```bash
chmod +x skills/my_tool.py
echo '{"param":"test"}' | ./skills/my_tool.py
```

### 4. Test with Orchestrator

```bash
./orchestrator/orchestrator_v2.py cloud "Use my tool with parameter test"
```

## Next Steps

Once everything works:

1. **Add more tools** for your specific use cases
2. **Create webhooks** to your home automation, APIs, etc.
3. **Build workflows** that chain multiple tools
4. **Add confirmation prompts** for critical operations
5. **Integrate MCP servers** for advanced capabilities

## Permissions Reference

```json
{
  "dangerous": true,      // Requires extra caution
  "bash": true,          // Executes shell commands
  "network": true,       // Makes HTTP requests
  "filesystem": true,    // Reads/writes files
  "auto_approve": false  // Always announce before executing
}
```

- `auto_approve: true` → Executes silently (for safe operations)
- `auto_approve: false` → Announces action (for network/bash/etc)
- `dangerous: true` → Always announces with warning

---

**Happy testing! 🚀**

