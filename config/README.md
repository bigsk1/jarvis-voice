# Jarvis Configuration

This directory contains configuration files for Jarvis Voice Assistant.

## Quick Start

1. **Choose your mode:**
   - **Cloud mode**: Uses Anthropic/OpenAI APIs (requires API keys, best performance)
   - **Local mode**: Uses Ollama (no API keys, runs offline, requires GPU)

2. **Copy the example file:**
   ```bash
   # For cloud mode:
   cp cloud.env.example cloud.env
   
   # For local mode:
   cp local.env.example local.env
   ```

3. **Edit your config file:**
   ```bash
   # Edit and add your API keys (cloud mode only)
   nano cloud.env
   # or
   nano local.env
   ```

4. **Run Jarvis:**
   ```bash
   # Cloud mode
   ./jarvis  # voice mode
   ./orchestrator/orchestrator_v2.py cloud "What time is it?"  # CLI
   
   # Local mode
   ./jarvis-local  # voice mode
   ./orchestrator/orchestrator_v2.py local "What time is it?"  # CLI
   ```

5. **(Optional) Configure MCP Servers:**
   - MCP servers add tools like web search (DuckDuckGo), HTTP fetch, etc.
   - Edit `config/mcp-servers.json` to enable/disable servers
   - See [MCP Server Configuration](#mcp-server-configuration) and [TOOL RAG IMPLEMENTATION SUMMARY](../docs/TOOL_RAG_IMPLEMENTATION_SUMMARY.md) and [MCP REMOTE TRANSPORT](../docs/MCP_REMOTE_TRANSPORT.md) for details
   - IF YOU MODIFY MCP SERVERS OR TOOLS MAKE SURE TO RE SYNC DB FOR TOOL RAG TO PICK UP NEW TOOLS

## Configuration Files

### `cloud.env` (Cloud Mode)
- **Uses**: Anthropic Claude or OpenAI GPT
- **Requires**: API keys (costs money per request)
- **Best for**: Production use, maximum accuracy, complex tasks
- **OpenCode**: Can use Claude (recommended) or OpenAI

### `local.env` (Local Mode)
- **Uses**: Ollama with local models (qwen3-vl recommended)
- **Requires**: GPU with 8GB+ VRAM
- **Best for**: Development, offline work, privacy, no API costs
- **OpenCode**: Can use local Ollama models OR Anthropic (safer)

### Example Files (Safe for Git)
- `cloud.env.example` - Template for cloud mode
- `local.env.example` - Template for local mode
- **Never commit** `cloud.env` or `local.env` (contains API keys!)

## Important Settings

### LLM Provider Selection

Note:
- Curated cloud model metadata for the Web UI, context labels, and cost/context helpers now comes from `lib/model_catalog.py`.
- If you point `OPENAI_MODEL`, `XAI_MODEL`, or `ANTHROPIC_MODEL` at a newer model that is not yet curated, Jarvis can still use it at runtime and the settings UI will show it as a custom model entry.

### Cloud Model Maintenance

Source of truth for curated cloud chat model metadata:
- `lib/model_catalog.py`

When adding a new curated cloud chat model:
1. Add it to `lib/model_catalog.py`
2. Include display name, context window, pricing, aliases if needed, and mark `default: true` only if it should become the curated fallback
3. Update docs/examples only if you want the new model surfaced in human-facing guidance

When removing an old curated cloud chat model:
1. Remove it from `lib/model_catalog.py`
2. Clean up docs/examples that still mention it
3. Keep or remove any fallback pricing in `lib/cost_estimator.py` depending on whether you still want historical/specialized cost estimation support

Notes:
- Ollama models are not curated here; they are still discovered/configured dynamically
- Image/video provider models are still managed in their existing provider-specific code paths

**Jarvis Tool Calling** (main LLM):
```bash
# Cloud mode
LLM_PROVIDER="anthropic"
ANTHROPIC_MODEL="claude-sonnet-4-5-20250929"

# Local mode
LLM_PROVIDER="ollama"
OLLAMA_MODEL="qwen3.5:latest"
```

**OpenCode Agent** (coding tasks):
```bash
# Recommended: Use Claude even in local mode (safer for code execution)
OPENCODE_PROVIDER="anthropic"
OPENCODE_MODEL="claude-sonnet-4-5-20250929"

# Experimental: Local Ollama models (less safe, less reliable)
OPENCODE_PROVIDER="ollama"
OPENCODE_MODEL="qwen3.5:latest"
```

### Response Style

```bash
JARVIS_RESPONSE_STYLE="auto"  # Recommended
# Options:
#   "auto" - Smart formatting based on context
#   "casual" - Always concise (8-12 words for voice)
#   "detailed" - Full LLM output (debugging)
```

## Security Notes

1. **API Keys**: Never commit files with real API keys
2. **Git Ignore**: The `.gitignore` should include:
   ```
   config/cloud.env
   config/local.env
   ```

3. **OpenCode Safety**: 
   - Local models can execute arbitrary code
   - Recommended: Use Claude for OpenCode even in local mode
   - Workspace is sandboxed to `/home/boss/jarvis-workspace`

## Troubleshooting

### "OpenCode server not reachable"
```bash
# Start OpenCode
systemctl --user start opencode

```

### "Ollama connection failed"
```bash
# Check Ollama status
curl http://localhost:11434
# Start Ollama
ollama serve
```

### "Model not found"
```bash
# Install recommended models
ollama pull qwen3.5:latest
ollama pull nomic-embed-text
```

## Advanced Configuration

### Network Setup (WireGuard VPN example)
```bash
# If services run on different machine:
OLLAMA_BASE_URL="http://localhost:11434"
OPENCODE_BASE_URL="http://localhost:4096"
```

### GPU Optimization
```bash
# Adjust for your VRAM (16GB example)
OLLAMA_CONTEXT_LENGTH=12888
MAX_CONTEXT_TOKENS=12888
```

### Ollama Embeddings
```bash
# Embeddings use the local Ollama embedding model
OLLAMA_EMBEDDING_MODEL="nomic-embed-text"

# Optional: override embedding num_ctx specifically for Ollama embed requests.
# If omitted, Jarvis reuses OLLAMA_CONTEXT_WINDOW.
OLLAMA_EMBEDDING_CONTEXT_WINDOW=8192
```

### Hybrid Mode
```bash
# Use Ollama for Jarvis, Claude for OpenCode
LLM_PROVIDER="ollama"  # Free, offline
OPENCODE_PROVIDER="anthropic"  # Paid, safer
```

---

## MCP Server Configuration

### Overview

**MCP (Model Context Protocol)** servers extend Jarvis with additional tools like web search, HTTP fetch, etc.

MCP servers can be configured to use the following transports:
- stdio: Local subprocess with stdin/stdout
- sse: Server-Sent Events over HTTP
- http: Streamable HTTP (JSON-RPC over HTTP POST)

The recommended transport is http.

**Important**: These MCP servers are for **Jarvis** only. OpenCode has its own MCP configuration at `~/.config/opencode/opencode.json`.


### Configuration File

**Location**: `config/mcp-servers.json`

This file is **committed to git**, so:
- ✅ Safe to include: Commands, descriptions, enabled status
- ❌ Never include: API keys, secrets, passwords

### Basic Example (No Secrets)

```json
{
  "mcpServers": {
    "duckduckgo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm", "--network", "host",
        "mcp/duckduckgo"
      ],
      "description": "Web search via DuckDuckGo",
      "enabled": true
    },
    "fetch": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm", "--network", "host",
        "mcp/fetch"
      ],
      "description": "Fetch URLs as markdown",
      "enabled": true
      // Note: No "env" key = no environment variables passed (secure by default)
    }
  }
}
```

**Security Note**: If you omit the `"env"` key or use `"env": {}`, **no environment variables** are passed to the MCP server. This is secure by default—the server won't have access to your API keys or secrets.

### MCP Server with API Key (Secure Pattern)

For MCP servers that need API keys, use environment variables from `cloud.env` or `local.env`:

**1. Add API key to your `.env` file:**

```bash
# In cloud.env or local.env (NOT committed to git)
WEATHER_API_KEY="your-secret-key-here"
OPENAI_API_KEY="sk-proj-abc123..."
```

**2. Reference in `mcp-servers.json`:**

```json
{
  "mcpServers": {
    "weather": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-weather"
      ],
      "env": {
        "WEATHER_API_KEY": "${WEATHER_API_KEY}"
      },
      "description": "Weather data from external API",
      "enabled": true
    },
    "openai-tools": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "OPENAI_API_KEY=${OPENAI_API_KEY}",
        "mcp/openai-tools"
      ],
      "description": "OpenAI-powered tools",
      "enabled": false
    }
  }
}
```

**How It Works:**
- `${VAR_NAME}` is replaced with the value from your `.env` file at runtime
- Only explicitly listed variables are passed to the MCP server
- The MCP server **does not** have access to other secrets (like `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)

**Security Benefits:**
- ✅ Least privilege: MCP servers only get what they need
- ✅ Secrets in `.env` files (not committed to git)
- ✅ No access to unrelated API keys or credentials

### Enable/Disable MCP Servers

Set `"enabled": false` to disable without deleting:

```json
{
  "mcpServers": {
    "experimental-server": {
      "command": "...",
      "enabled": false  // Temporarily disabled
    }
  }
}
```

### Jarvis vs OpenCode MCP Servers

| Feature | Jarvis MCP | OpenCode MCP |
|---------|------------|--------------|
| **Config Location** | `config/mcp-servers.json` | `~/.config/opencode/opencode.json` |
| **Used By** | Jarvis tool system | OpenCode autonomous agent |
| **Startup** | Auto-discovered on Jarvis startup | Loaded by OpenCode server |
| **Tool Prefix** | `mcp_<server>_<tool>` | Used directly by OpenCode |
| **Environment** | Loads from `cloud.env` or `local.env` | Uses system environment |
| **Testing** | `./bin/test-mcp --discover` | OpenCode UI or API |

**Example**: A DuckDuckGo search in Jarvis becomes `mcp_duckduckgo_search`, but OpenCode uses it as `search()` directly.

**Security Note**: Jarvis and OpenCode have separate MCP configurations. Inspect tools separately:
- Jarvis: `./bin/test-mcp --discover`
- OpenCode: Check `~/.config/opencode/opencode.json` and OpenCode documentation

### Testing & Inspecting MCP Servers

**SECURITY: Always inspect MCP tools BEFORE enabling them in production!**

Use the `test-mcp` script to safely discover what tools an MCP server exposes:

```bash
# 1. List all configured servers (shows enabled/disabled status)
./bin/test-mcp --list

# 2. Discover tools from enabled servers (SAFE - doesn't give Jarvis access yet)
./bin/test-mcp --discover

# 3. Inspect tools for security issues (look for dangerous capabilities)
#    Watch for tools that:
#    - Access filesystem (read_file, write_file, execute_command)
#    - Execute shell commands (exec, bash, run_command)
#    - Access sensitive directories (.ssh, /etc, ~/.aws)
#    - Make arbitrary HTTP requests to internal networks
./bin/test-mcp --discover | grep -i "execute\|bash\|command\|file\|ssh"

# 4. Test a specific tool safely (before using in Jarvis)
./bin/test-mcp --test brave-search brave_web_search '{"query": "test"}'

# 5. After inspection, test with Jarvis (this uses the tool for real)
./orchestrator/orchestrator_v2.py cloud "Search for bitcoin price"
```

**Security Checklist:**
- ✅ Run `--discover` to see ALL tools before enabling
- ✅ Check tool descriptions for dangerous keywords (execute, bash, file access)
- ✅ Verify environment variables are only passed to trusted servers
- ✅ Test unknown MCP servers in isolated environment first
- ✅ Review parameter names (look for `command`, `path`, `filename`, `code`)
- ✅ Disable servers you don't need (`"enabled": false`)

**Red Flags (Potentially Dangerous Tools):**
- Tool names like: `execute_command`, `run_bash`, `write_file`, `read_ssh_key`
- Parameters like: `command`, `code`, `script`, `filepath`, `directory`
- Descriptions mentioning: "executes", "runs code", "accesses filesystem"

**📖 For detailed security audit guide, see:** [`docs/MCP_SECURITY_AUDIT.md`](../docs/MCP_SECURITY_AUDIT.md)

### Troubleshooting

**MCP servers not loading:**
```bash
# Check Docker is running (for Docker-based MCP servers)
docker ps

# Check mcp-servers.json syntax
cat config/mcp-servers.json | jq .

# Discover what's actually loaded
./bin/test-mcp --list

# See tools from enabled servers
./bin/test-mcp --discover

# Check Jarvis logs
cat logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | grep mcp_
```

**MCP server fails to start:**
```bash
# Test the server individually
./bin/test-mcp --test <server-name> <tool-name> '{"param": "value"}'

# Check Docker logs (if using Docker)
docker logs $(docker ps -a | grep mcp/<server-name> | awk '{print $1}')

# Verify API keys are loaded
echo $BRAVE_API_KEY  # Should show your API key
```

**Environment variables not loading:**
- Ensure variable is defined in `cloud.env` or `local.env`
- Use exact syntax: `${VAR_NAME}` (not `$VAR_NAME` or `%VAR_NAME%`)
- Variable must be explicitly listed in the `"env"` block
- Test substitution: `./bin/test-mcp --discover` shows if env vars are passed
- Restart Jarvis after changing `.env` files

**Security audit:**
```bash
# Inspect all tools for dangerous capabilities
./bin/test-mcp --discover | grep -E "(execute|command|bash|file|ssh|write|delete)"

# Verify only intended vars are passed
./bin/test-mcp --list  # Shows which env vars each server gets

# Check that disabled servers don't load
./bin/test-mcp --list | grep DISABLED
```

---

## Model Recommendations

### Cloud Mode (Anthropic)
- **Best overall**: `claude-sonnet-4-5-20250929`
- **Fastest**: `claude-sonnet-4-20250514`
- **Legacy**: `claude-3-7-sonnet-20250219`

### Local Mode (Ollama)
- **Best for Jarvis**: `qwen3` (8B, 256K context, excellent tool calling)
- **Best for OpenCode**: Use Claude API (more reliable)
- **Experimental OpenCode**: `qwen3.5:latest` (13gb of VRAM)

## Quick Reference

**Configuration Files:**
- `cloud.env` / `local.env` - Main config (API keys, settings)
- `mcp-servers.json` - MCP server configuration (Jarvis)
- `~/.config/opencode/opencode.json` - OpenCode config (including MCP)

**Key Concepts:**
- API keys go in `.env` files (not committed to git)
- MCP servers can reference `.env` variables via `${VAR_NAME}`
- **Security**: Only explicitly listed `env` vars are passed (least privilege)
- Jarvis and OpenCode have separate MCP configurations

**Testing MCP Servers:**
```bash
./bin/test-mcp --list       # List all servers (enabled/disabled)
./bin/test-mcp --discover   # Discover tools (SAFE inspection)
./bin/test-mcp --all         # Full overview (list + discover)
```

## Support

For issues, see:
- Main README: `/home/boss/jarvis-voice/README.md`
- MCP Security: `/home/boss/jarvis-voice/docs/MCP_SECURITY_AUDIT.md`
- MCP Quickstart: `/home/boss/jarvis-voice/docs/MCP_QUICKSTART.md`
- Docs: `/home/boss/jarvis-voice/docs/`
- Logs: `/home/boss/jarvis-voice/logs/`
