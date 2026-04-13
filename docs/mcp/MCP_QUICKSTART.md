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

MCP (Model Context Protocol) servers are **pre-built tools** you can add to Jarvis instantly:

- **`mcp/duckduckgo`** - Web search + content fetching
- **`mcp/filesystem`** - File operations
- **`mcp/github`** - GitHub integration
- **`mcp/postgres`** - Database access
- Many more...

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
# One command!
docker pull mcp/duckduckgo
# Done! Now you have web search.
```

## 3. Testing MCP (DuckDuckGo Example)

### Prerequisites
- Docker installed and running
- Pull the MCP server image:

```bash
docker pull mcp/duckduckgo
```

### Test MCP Server

```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
./bin/test-mcp --server
```

**Expected output:**
```
🧪 Testing DuckDuckGo MCP Server
🚀 Starting MCP server...
✅ Server started

📋 Listing available tools...
✅ Found 2 tools:

  Tool: search
  Description: Search DuckDuckGo and return formatted results
  
  Tool: fetch_content
  Description: Fetch and parse content from a webpage URL

🔍 Testing search tool...
✅ Result: [Search results about bitcoin price...]

✅ MCP server test successful!
```

## 4. Adding MCP Servers

### Option A: Docker MCP (Recommended)

Edit `config/mcp-servers.json`:

```json
{
  "mcpServers": {
    "duckduckgo": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/duckduckgo"],
      "description": "Web search via DuckDuckGo",
      "enabled": true
    },
    "filesystem": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v",
        "~:/workspace",
        "mcp/filesystem"
      ],
      "description": "File system operations",
      "enabled": false
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

Once integrated (Phase 2, coming next), you'll be able to:

```
"Hey Jarvis"
"Search the web for bitcoin news"
  ↓
Jarvis: [Uses mcp.duckduckgo.search]
"Here are the latest bitcoin news..."

"Hey Jarvis"  
"Fetch content from https://example.com"
  ↓
Jarvis: [Uses mcp.duckduckgo.fetch_content]
"The page contains..."
```

## 6. Available MCP Servers

### Search & Web
- **`mcp/duckduckgo`** ✅ No API key needed
  - Tools: `search`, `fetch_content`
- **`mcp/brave-search`** Requires Brave API key
  - Tools: `search`
- **`mcp/exa`** Requires Exa API key
  - Tools: `search`

### Development
- **`mcp/github`** Requires GitHub token
  - Tools: `create_issue`, `search_repos`, `get_pr`, etc.
- **`mcp/gitlab`** Requires GitLab token
  - Tools: Similar to GitHub

### Filesystem
- **`mcp/filesystem`** No API key
  - Tools: `read_file`, `write_file`, `list_directory`

### Databases
- **`mcp/postgres`** Requires DB connection
  - Tools: `query`, `execute`
- **`mcp/sqlite`** No API key
  - Tools: `query`, `execute`

### Communication
- **`mcp/slack`** Requires Slack token
  - Tools: `send_message`, `list_channels`

## 7. Current Implementation Status

### ✅ Completed
- [x] Tool listing on startup (auto-updates!)
- [x] MCP client library (JSON-RPC communication)
- [x] MCP configuration format
- [x] Test script for validation
- [x] Documentation


## 8. Architecture

```
Voice: "Hey Jarvis, search for bitcoin news"
  ↓
STT → Transcript
  ↓
Claude Sonnet 4.5
  ↓ (sees all tools)
┌─────────────┬─────────────┐
↓             ↓
Local Tools   MCP Tools
get_time      mcp.duckduckgo.search ← Uses MCP client
crypto_price  mcp.duckduckgo.fetch  ← Via Docker
execute_bash  mcp.github.create_issue
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
- ✅ Reuse connections (coming in Phase 2)
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
- [ ] Pull MCP server: `docker pull mcp/duckduckgo`
- [ ] Test connectivity: `./bin/test-mcp --server`
- [ ] Check config: `cat config/mcp-servers.json`
- [ ] Verify tools appear: `jarvis` (should show in tool list)

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
docker run -i --rm mcp/duckduckgo

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

## 12. Example: Add DuckDuckGo to Jarvis

**Step 1:** Pull Docker image
```bash
docker pull mcp/duckduckgo
```

**Step 2:** Enable in config
```bash
# Edit config/mcp-servers.json
"duckduckgo": {
  ...
  "enabled": true  ← Change this
}
```

**Step 3:** Test
```bash
./bin/test-mcp --list --mode cloud --all
```

**Step 4:** Use with voice (Phase 2)
```
"Hey Jarvis"
"Search for Anthropic Claude Sonnet 4"
```

## 13. Recommendations

### Start With
1. **DuckDuckGo** - No API key, useful for web search
2. **Filesystem** - Useful for file operations (be careful with mounts!)

### Avoid Initially
1. Paid API services (Brave, Exa) - Until you test free ones
2. Database MCPs - Need careful configuration
3. Too many servers - Start with 1-2, add more later

### Best Practices
1. Test MCP servers individually first (`test-mcp`)
2. Start with `"enabled": false`, enable after testing
3. Use specific volume mounts, not full filesystem
4. Review MCP server docs before using
5. Monitor logs for unusual activity

---

**You now have a modular, extensible tool system!** 🚀

Next: Phase 2 will integrate MCP tools into the voice interface.

