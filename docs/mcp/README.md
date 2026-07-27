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
docker pull ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0
docker pull mcp/brave-search
docker pull mcp/fetch
```

### 2. Configure in `config/mcp-servers.json`

```json
{
  "mcpServers": {
    "duckduckgo": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--user", "65534:65534",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-e", "DDG_REGION",
        "-e", "DDG_SAFE_SEARCH",
        "ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0"
      ],
      "env": {
        "DDG_REGION": "us-en",
        "DDG_SAFE_SEARCH": "STRICT"
      },
      "proxy_policy": "prefer",
      "enabled": true
    }
  }
}
```

`proxy_policy: "prefer"` makes Jarvis choose the first reachable
`LOCAL_PROXY` / `LOCAL_PROXY2` listener and pass only derived conventional
proxy variables into the DuckDuckGo container. Omit the field to preserve an
MCP server's existing behavior; use `off` for direct-only or `require` to fail
closed without direct fallback. See [Network proxy](../NETWORK_PROXY.md).

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
- `mcp_duckduckgo_search`
- `mcp_duckduckgo_fetch_content`
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

MCP tool execution errors are distinct from JSON-RPC transport errors. When a
server returns a `CallToolResult` with `isError: true`, Jarvis preserves the
server's text for diagnostics but reports `ok: false` to the orchestrator so
workflows and the routing model cannot mistake the error payload for valid
tool data. This behavior is shared by stdio, SSE, and Streamable HTTP clients.

The community DuckDuckGo server currently reports some failures as ordinary
text while leaving MCP `isError` false. Jarvis narrowly recognizes its known
`search` and `fetch_content` error prefixes and also reports those as
`ok: false`; other MCP servers are not reclassified from arbitrary `Error:`
text.

### Persisted Web Follow-ups

The active orchestration run receives the complete MCP result. Saved Web
conversation context is intentionally smaller:

- DuckDuckGo search retains queries, result counts, URLs, titles, and snippets.
- DuckDuckGo and Fetch retrieval retain the URL, pagination/backend arguments,
  and at most a 2,000-character head/tail excerpt.
- Completion Guard receives the same compact search candidates as grounding
  evidence.

The original tool result remains in the saved message data for inspection; the
compact projection is what is replayed into later routing prompts.

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
- ✅ `proxy_policy=prefer|require` adds only conventional proxy names derived
  from `LOCAL_PROXY` / `LOCAL_PROXY2`; it does not copy the host environment

### Auditing New Servers

```bash
# Check for dangerous tools
./bin/test-mcp --discover | grep -E "(execute|command|bash|file)"
```

See [MCP_SECURITY_AUDIT.md](./MCP_SECURITY_AUDIT.md) for full checklist.

### External-Content Trust Boundary

Search and fetch tools return untrusted Internet content. SafeSearch reduces
adult-content exposure; it does not verify ownership, prevent search poisoning,
or certify that a result is not a typosquat or phishing page. For claimed
official sources, verify the registrable domain independently before trusting
instructions, downloads, login forms, or API-key requests.

The tracked DuckDuckGo configuration adds container hardening (`65534:65534`,
read-only root filesystem, all capabilities dropped, and
`no-new-privileges`). Its fetch tool also blocks private/loopback targets and
re-validates redirects upstream. These controls reduce local and SSRF risk but
do not make fetched content authoritative.

---

## 🐳 Container Management

### View Running MCP Containers

```bash
docker ps --filter "ancestor=ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0" \
  --filter "ancestor=mcp/brave-search" \
  --filter "ancestor=mcp/fetch"
```

### Update MCP Images

```bash
docker pull ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0
docker pull mcp/brave-search
docker pull mcp/fetch
# Restart jarvis-web to pick up new images
```

### Cleanup Orphaned Containers

```bash
# Stop all MCP containers
docker ps --filter "ancestor=ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0" -q | xargs -r docker stop
docker ps --filter "ancestor=mcp/brave-search" -q | xargs -r docker stop
docker ps --filter "ancestor=mcp/fetch" -q | xargs -r docker stop
```

---

## 📡 Currently Enabled Servers

| Server | Docker Image | Tools |
|--------|--------------|-------|
| `brave_search` | `mcp/brave-search` | Web, local, image, and video search (`brave_news_search` is disabled in the tracked config) |
| `duckduckgo` | `ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0` | `search`, `fetch_content` (credential-free; US English + Strict SafeSearch defaults; `proxy_policy=prefer`) |
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
# Exercise one tool through Jarvis's MCP client
./bin/test-mcp --test duckduckgo search \
  '{"query":"official Python documentation","max_results":3}'

# Brave only: check if its API key is set
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
docker ps --filter "ancestor=ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0" -q | xargs -r docker stop
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
| `jarvis-web/server/services/followup_extractor.py` | Compact persisted follow-up/evidence projection |
| `bin/test-mcp` | Testing and debugging script |
| `tests/test_mcp_tool_errors.py` | Standard and DuckDuckGo MCP error semantics |
| `tests/test_chat_followup_serpapi.py` | Persisted search/fetch follow-up and evidence regression coverage |

---

## 📖 Further Reading

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Anthropic MCP Guide](https://docs.anthropic.com/en/docs/agents-and-tools/mcp)
- [Docker MCP Images](https://hub.docker.com/u/mcp)
- [Upstream DuckDuckGo MCP container](https://github.com/nickclyde/duckduckgo-mcp-server/pkgs/container/duckduckgo-mcp-server)
- [DuckDuckGo MCP upstream source](https://github.com/nickclyde/duckduckgo-mcp-server)

---

*Last verified: July 27, 2026 against `config/mcp-servers.json`,
`lib/mcp_client.py`, `lib/tool_schema.py`,
`jarvis-web/server/services/followup_extractor.py`, and the upstream v0.6.0
container metadata.*
