# MCP (Model Context Protocol) Integration

> **MCP** enables Jarvis to use external tools via a standardized protocol. This allows drop-in capabilities like web search, browser automation, and more without writing custom code.

---

## 📚 Documentation Index

| Document | Description |
|----------|-------------|
| [MCP_QUICKSTART.md](./MCP_QUICKSTART.md) | Getting started, adding servers, testing |
| [MCP_NAMING_CONVENTIONS.md](./MCP_NAMING_CONVENTIONS.md) | **Critical**: Use snake_case for server names |
| [MCP_REMOTE_TRANSPORT.md](./MCP_REMOTE_TRANSPORT.md) | SSE and Streamable HTTP transport setup |
| [MCP_SECURITY_AUDIT.md](./MCP_SECURITY_AUDIT.md) | Security best practices, auditing tools |
| [MCP_REGRESSION_FIX.md](./MCP_REGRESSION_FIX.md) | Parser fix for underscore server names |

---

## 🚀 Quick Start

### 1. Pull a Docker MCP Server

```bash
docker pull mcp/brave-search
docker pull mcp/fetch
```

### 2. Configure in `config/mcp-servers.json`

```json
{
  "mcpServers": {
    "brave_search": {
      "command": "docker",
      "args": ["run", "-e", "BRAVE_API_KEY", "-i", "--rm", "--network", "host", "mcp/brave-search"],
      "env": { "BRAVE_API_KEY": "${BRAVE_API_KEY}" },
      "enabled": true
    }
  }
}
```

> ⚠️ **Critical**: Server names MUST use `snake_case` (e.g., `brave_search`, not `brave-search`). See [MCP_NAMING_CONVENTIONS.md](./MCP_NAMING_CONVENTIONS.md).

### 3. Test

```bash
./bin/test-mcp --list
./bin/test-mcp --discover
```

---

## 🏗️ Architecture

### Transport Types

| Type | Use Case | Example |
|------|----------|---------|
| **stdio** | Docker containers, local CLI tools | `mcp/brave-search` |
| **http** | Remote MCP servers (modern) | CoinGecko API |
| **sse** | Remote MCP servers (legacy) | Older implementations |

### Tool Naming

MCP tools follow this format:
```
mcp_{server_name}_{tool_name}
```

Examples:
- `mcp_brave_search_brave_web_search`
- `mcp_fetch_fetch`

---

## 🔧 Reliability Features

### Singleton Pattern (Prevents Container Multiplication)

**Problem**: Web UI was spawning new MCP Docker containers per message.

**Solution**: `ToolRegistry` is now a singleton shared across all requests.

```python
# lib/tool_schema.py
from tool_schema import get_tool_registry

# Returns shared instance - only creates MCP containers once
registry = get_tool_registry(mode='cloud')
```

**Behavior**:
- **Web UI**: Containers start once and stay alive for all messages
- **Terminal**: Containers start for the session and cleanup on exit
- **Mode switch**: Containers cleanup and restart with new mode

### Crash Recovery (Auto-Restart with Loop Protection)

**Problem**: If an MCP container crashes, subsequent tool calls fail.

**Solution**: Health check before each request with automatic restart.

```python
# lib/mcp_client.py - MCPClient class
MAX_RESTART_ATTEMPTS = 3       # Max restarts before cooldown
RESTART_COOLDOWN_SECONDS = 60  # Wait after hitting max
```

**Behavior**:

| Scenario | Action |
|----------|--------|
| Container running | ✅ Proceed normally |
| Container crashed (1st-3rd time) | 🔄 Auto-restart |
| Container crashed (4th+ time) | 🛑 60s cooldown, fail gracefully |
| After cooldown expires | 🔄 Counter resets, can retry |

**Console output**:
```
⚠️ MCP brave_search crashed (exit code: 137)
🔄 Restarting MCP brave_search (attempt 1/3)...
✅ MCP brave_search restarted successfully
```

---

## 🔒 Security

### Environment Variable Isolation

MCP servers only receive **explicitly configured** environment variables:

```json
"env": {
  "BRAVE_API_KEY": "${BRAVE_API_KEY}"
}
```

- ✅ Only `BRAVE_API_KEY` is passed
- ❌ `SSH_AUTH_SOCK`, `AWS_SECRET_KEY`, etc. are **never exposed**

### Auditing New Servers

```bash
# Check for dangerous tools
./bin/test-mcp --discover | grep -E "(execute|command|bash|file)"
```

See [MCP_SECURITY_AUDIT.md](./MCP_SECURITY_AUDIT.md) for full checklist.

---

## 🐳 Container Management

### View Running MCP Containers

```bash
docker ps --filter "ancestor=mcp/brave-search" --filter "ancestor=mcp/fetch"
```

### Update MCP Images

```bash
docker pull mcp/brave-search
docker pull mcp/fetch
# Restart jarvis-web to pick up new images
```

### Cleanup Orphaned Containers

```bash
# Stop all MCP containers
docker ps --filter "ancestor=mcp/brave-search" -q | xargs -r docker stop
docker ps --filter "ancestor=mcp/fetch" -q | xargs -r docker stop
```

---

## 📡 Currently Enabled Servers

| Server | Docker Image | Tools |
|--------|--------------|-------|
| `brave_search` | `mcp/brave-search` | Web, local, news, image, video search |
| `fetch` | `mcp/fetch` | URL content extraction |

### Disabled (Available)

| Server | Docker Image | Use Case |
|--------|--------------|----------|
| `sequentialthinking` | `mcp/sequentialthinking` | Step-by-step reasoning |
| `playwright` | `mcr.microsoft.com/playwright/mcp` | Browser automation |

---

## 🔍 Troubleshooting

### Containers Not Starting

```bash
# Test manually
docker run -i --rm mcp/brave-search

# Check if API key is set
echo $BRAVE_API_KEY
```

### "MCP server in cooldown" Error

The container crashed 3+ times. Wait 60 seconds or restart jarvis-web.

### Tools Not Appearing

```bash
# Verify config
cat config/mcp-servers.json

# Check enabled flag
jq '.mcpServers | keys' config/mcp-servers.json
```

### Multiple Containers Running

If you see duplicate containers:
```bash
# Stop all
docker ps --filter "ancestor=mcp/brave-search" -q | xargs -r docker stop
docker ps --filter "ancestor=mcp/fetch" -q | xargs -r docker stop

# Restart jarvis-web (uses singleton now)
```

---

## 📁 Related Files

| File | Purpose |
|------|---------|
| `config/mcp-servers.json` | Server configuration |
| `lib/mcp_client.py` | MCP client (stdio, SSE, HTTP transports) |
| `lib/tool_schema.py` | Tool discovery, singleton registry |
| `bin/test-mcp` | Testing and debugging script |

---

## 📖 Further Reading

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Anthropic MCP Guide](https://docs.anthropic.com/en/docs/agents-and-tools/mcp)
- [Docker MCP Images](https://hub.docker.com/u/mcp)

---

*Last updated: December 2025 (v2.19 - Singleton pattern, crash recovery)*

