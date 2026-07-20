#MCP Integration - Quick Start

## What Was Added

✅ **Tool listing on startup** - Auto-displays all available tools when Jarvis starts
✅ **MCP client library** - Communicates with MCP servers via JSON-RPC
✅ **MCP configuration** - Easy config file to add/remove MCP servers
✅ **Test script** - Verify MCP connectivity before integration

## 1. Tool Listing Feature

**What it does:** When you start Jarvis, it now shows all available tools!

```bash
jarvis
```

**Output:**
```
🛠️  Available Tools:
  1. ✅ check_tool_logs       - Check recent tool execution logs...
  2. 🌐 crypto_price          - Get current cryptocurrency price...
  3. ⚡ execute_bash          - Execute a bash command...
  4. ✅ get_time              - Get current date and time...
  5. 🌐 send_webhook          - Send a POST request webhook...
```

**Icons:**
- ✅ = Safe (auto-approved)
- 🌐 = Network access
- ⚡ = Bash execution
- 🚨 = Dangerous operation

## 2. MCP Integration (Ready to Use!)

### What Are MCP Servers?

MCP (Model Context Protocol) servers are **pre-built tools** you can add to Jarvis instantly.

**Shipped enabled servers** (`config/mcp-servers.json`):
- **`mcp/fetch`** - Fetch URL content as markdown
- **`mcp/brave-search`** - Web search (requires `BRAVE_API_KEY`)

Optional (present but disabled by default): `sequentialthinking`, `playwright`.

### Why Use MCP Servers?

**Traditional approach:**
```bash
# You write a custom tool
1. Create tool script (50+ lines of code)
2. Create tool schema
3. Test thoroughly
4. Debug edge cases
```

**MCP approach:**
```bash
# Pull the shipped images
docker pull mcp/fetch
docker pull mcp/brave-search
# Enable in config/mcp-servers.json — tools appear in Jarvis (voice, web, CLI)
```

## 3. Testing MCP (Shipped Servers)

### Prerequisites
- Docker installed and running
- Pull the enabled server images:

```bash
docker pull mcp/fetch
docker pull mcp/brave-search
```

### Test MCP Server

```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
./bin/test-mcp --discover
```

**Expected output** (varies by enabled servers):
```
🛠️  Discovering Tools from Enabled Servers
======================================================================
📡 Loading cloud mode config...
🔌 Starting MCP servers...

✅ Loaded N enabled server(s)

⏳ Querying fetch (stdio)...
   ✅ Found N tool(s)

📚 Tool Catalog
======================================================================

🔧 fetch [stdio]
----------------------------------------------------------------------

  Tool: mcp_fetch_...
```

Use `./bin/test-mcp --list` to list configured servers, or `./bin/test-mcp --all` for list + discover + audit.

## 4. Adding MCP Servers

### Option A: Docker MCP (Recommended)

Edit `config/mcp-servers.json` (shipped shape):

```json
{
  "mcpServers": {
    "fetch": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--network", "host", "mcp/fetch", "--ignore-robots-txt"],
      "description": "Fetch URL content as markdown",
      "enabled": true
    },
    "brave_search": {
      "command": "docker",
      "args": ["run", "-e", "BRAVE_API_KEY", "-i", "--rm", "--network", "host", "mcp/brave-search"],
      "env": { "BRAVE_API_KEY": "${BRAVE_API_KEY}" },
      "description": "Web search via Brave",
      "enabled": true
    }
  }
}
```

### Option B: Native MCP (npm)

```json
{
  "mcpServers": {
    "brave_search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-api-key"
      },
      "description": "Web search via Brave",
      "enabled": false
    }
  }
}
```

## 5. Using MCP Tools with Voice

MCP tools are already integrated into voice, web, and CLI once servers are enabled. Example:

```
"Hey Jarvis"
"Search the web for bitcoin news"
  ↓
Jarvis: [Uses mcp_brave_search_...]
"Here are the latest bitcoin news..."

"Hey Jarvis"
"Fetch content from https://example.com"
  ↓
Jarvis: [Uses mcp_fetch_...]
"The page contains..."
```

## 6. Available MCP Servers (Shipped Config)

### Enabled by default
- **`fetch`** (`mcp/fetch`) — URL content as markdown
- **`brave_search`** (`mcp/brave-search`) — Web search (needs `BRAVE_API_KEY`)

### Present but disabled by default
- **`sequentialthinking`** — Step-by-step reasoning
- **`playwright`** — Browser automation for JS-heavy sites

You can add other community MCP servers to `config/mcp-servers.json` the same way.

## 7. Current Implementation Status

### ✅ Completed
- [x] Tool listing on startup
- [x] MCP client library (JSON-RPC communication)
- [x] MCP configuration format (`config/mcp-servers.json`)
- [x] Test script for validation (`./bin/test-mcp`)
- [x] Voice / Web / CLI integration (tools appear in the router catalog)
- [x] Documentation


## 8. Architecture

```
Voice: "Hey Jarvis, search for bitcoin news"
  ↓
STT → Transcript
  ↓
Routing LLM (configured provider/model)
  ↓ (sees local + MCP tools)
┌─────────────┬─────────────┐
↓             ↓
Local Tools   MCP Tools
get_time      mcp_brave_search_...  ← Uses MCP client
crypto_price  mcp_fetch_...         ← Via Docker
execute_bash
  ↓
Execute & Return Result
  ↓
TTS → Voice Response
```

## 9. Why This Design?

### Modularity
- ✅ Drop-in MCP servers (no code changes)
- ✅ Local tools work independently
- ✅ Easy to enable/disable servers

### Performance
- ✅ Docker MCP servers are isolated
- ✅ Fast enough for voice interaction (~100-300ms)

### Security
- ✅ MCP servers are sandboxed in Docker
- ✅ Explicit volume mounts only
- ✅ Can review MCP server code before using

### Extensibility
- ✅ Anyone can create MCP servers
- ✅ Standard protocol (JSON-RPC)
- ✅ Language-agnostic (Python, JS, Go, Rust...)

## 10. Testing Checklist

Before using MCP in production:

- [ ] Docker is installed and running
- [ ] Pull shipped images: `docker pull mcp/fetch` and `docker pull mcp/brave-search`
- [ ] Test connectivity: `./bin/test-mcp --discover`
- [ ] Check config: `cat config/mcp-servers.json`
- [ ] Verify tools appear: start Jarvis (should show MCP tools in the catalog)

## 11. Troubleshooting

### Docker not running
```bash
# Check Docker status
docker ps

# Start Docker Desktop (if on Ubuntu Desktop)
systemctl start docker
```

### MCP server fails to start
```bash
# Test manually
docker run -i --rm mcp/fetch --ignore-robots-txt

# Check logs
docker logs <container-id>
```

### Tools not appearing
```bash
# Verify config
cat config/mcp-servers.json

# Check enabled flag
# Should be: "enabled": true
```

## 12. Example: Verify Shipped MCP Servers

**Step 1:** Pull Docker images
```bash
docker pull mcp/fetch
docker pull mcp/brave-search
```

**Step 2:** Confirm enabled in config
```bash
# Edit config/mcp-servers.json if needed
# fetch and brave_search should have "enabled": true
```

**Step 3:** Test
```bash
./bin/test-mcp --all --mode cloud
```

**Step 4:** Use with voice / web / CLI
```
"Hey Jarvis"
"Search for Anthropic Claude Sonnet 5"
```

## 13. Recommendations

### Start With
1. **fetch + brave_search** — shipped defaults (set `BRAVE_API_KEY` for search)
2. **playwright** — enable only when you need JS-heavy browsing

### Avoid Initially
- Broad filesystem mounts until you understand volume security
- Unreviewed third-party MCP images
- Too many servers at once — start with the shipped two, add more later

### Best Practices
1. Test MCP servers individually first (`./bin/test-mcp`)
2. Start with `"enabled": false`, enable after testing
3. Use specific volume mounts, not full filesystem
4. Review MCP server docs before using
5. Monitor logs for unusual activity

---

MCP tools are live in the orchestrator once enabled — no separate voice-integration step.

