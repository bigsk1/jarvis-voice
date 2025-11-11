# MCP (Model Context Protocol) Integration

## Overview

MCP servers provide pre-built tools that can be easily integrated into Jarvis. They communicate via JSON-RPC over stdin/stdout, making them language-agnostic.

## Architecture

```
Jarvis
  ↓
Tool Registry (Enhanced)
  ↓
┌─────────────┬─────────────┬─────────────┐
↓             ↓             ↓
Local Tools   MCP Tools     Future (API, etc.)
              ↓
      ┌───────┴───────┐
      ↓               ↓
  Docker MCP      Native MCP
  (mcp/*)         (npm, python)
```

## MCP Server Types

### 1. Docker MCP Servers (Recommended)
**Pros:**
- Pre-built, ready to use
- Isolated (no dependency conflicts)
- Easy to add/remove (`docker pull mcp/duckduckgo`)
- Works across all platforms

**Cons:**
- Requires Docker running
- Slight overhead (~50-100ms startup)
- Network isolation (may need host network)

**Examples:**
- `mcp/duckduckgo` - Web search
- `mcp/filesystem` - File operations
- `mcp/postgres` - Database access
- `mcp/github` - GitHub operations

### 2. Native MCP Servers
**Pros:**
- Faster (no Docker overhead)
- Direct system access

**Cons:**
- Need to install dependencies (npm, python packages)
- Platform-specific
- Potential conflicts

**Examples:**
- `@modelcontextprotocol/server-filesystem` (npm)
- Python MCP servers

## Configuration

### MCP Server Config

`config/mcp-servers.json`:
```json
{
  "mcpServers": {
    "duckduckgo": {
      "type": "docker",
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/duckduckgo"],
      "description": "Web search via DuckDuckGo"
    },
    "filesystem": {
      "type": "docker",
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "/home/boss:/workspace", "mcp/filesystem"],
      "description": "File system operations"
    },
    "brave_search": {
      "type": "npm",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-api-key"
      },
      "description": "Web search via Brave"
    }
  }
}
```

## Tool Discovery Flow

```python
# 1. Scan local tools (existing)
local_tools = discover_local_tools("skills/")

# 2. Scan MCP servers (new)
mcp_config = load_mcp_config("config/mcp-servers.json")
for server_name, config in mcp_config.items():
    # Start MCP server
    server = start_mcp_server(config)
    
    # List available tools via MCP protocol
    tools = server.list_tools()
    
    # Register as "mcp.duckduckgo.search", "mcp.duckduckgo.fetch_content"
    for tool in tools:
        register_tool(f"mcp.{server_name}.{tool.name}", tool)

# 3. Present unified tool list to Claude
all_tools = local_tools + mcp_tools
```

## Implementation Strategy

### Phase 1: MCP Client (Core)
Create MCP client that can:
- Start MCP server process
- Communicate via JSON-RPC
- List available tools
- Execute tool calls
- Handle errors

### Phase 2: Tool Registry Extension
- Discover MCP tools at startup
- Namespace them: `mcp.{server}.{tool}`
- Convert MCP tool schemas to our format
- Cache tool list (avoid restarting servers)

### Phase 3: Execution
- Route tool calls to appropriate server
- Handle stdin/stdout communication
- Parse JSON-RPC responses
- Log executions (same as local tools)

## MCP Protocol Basics

### 1. Initialize Server
```bash
docker run -i --rm mcp/duckduckgo
```

### 2. List Tools (JSON-RPC)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "search",
        "description": "Search DuckDuckGo and return formatted results",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query": {"type": "string", "description": "Search query"}
          },
          "required": ["query"]
        }
      }
    ]
  }
}
```

### 3. Call Tool
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "search",
    "arguments": {
      "query": "bitcoin price"
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Bitcoin is currently $105,000..."
      }
    ]
  }
}
```

## Example: DuckDuckGo MCP Server

### Configuration
```json
{
  "mcpServers": {
    "duckduckgo": {
      "type": "docker",
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/duckduckgo"]
    }
  }
}
```

### Usage (Voice)
```
"Hey Jarvis"
"Search the web for bitcoin news"
  ↓
Claude sees: mcp.duckduckgo.search tool
  ↓
Calls: mcp.duckduckgo.search(query="bitcoin news")
  ↓
MCP server executes search
  ↓
Returns: "Here are the latest bitcoin news..."
```

### Tool List Display
```
🛠️  Available Tools:
  1. ✅ check_tool_logs       - Check recent tool execution logs...
  2. 🌐 crypto_price          - Get current cryptocurrency price...
  3. ⚡ execute_bash          - Execute a bash command...
  4. ✅ get_time              - Get current date and time...
  5. 🔍 mcp.duckduckgo.search - Search DuckDuckGo...  ⭐ MCP
  6. 🔍 mcp.duckduckgo.fetch  - Fetch webpage content... ⭐ MCP
```

## Pros & Cons: Docker vs Native

### Docker MCP Servers ✅ RECOMMENDED

**Pros:**
- ✅ One command to add: `docker pull mcp/server-name`
- ✅ No dependency conflicts
- ✅ Consistent across systems
- ✅ Easy cleanup: `docker rm`
- ✅ Pre-tested and working

**Cons:**
- ⚠️ Need Docker running (you have Docker Desktop)
- ⚠️ Slight overhead (~50-100ms per call)
- ⚠️ Memory usage (one container per server)

**Recommendation**: Start with Docker, optimize later if needed.

### Native MCP Servers (npm, Python)

**Pros:**
- ✅ Faster (no Docker)
- ✅ Lower memory footprint

**Cons:**
- ❌ Need to install dependencies (npm install, pip install)
- ❌ Potential version conflicts
- ❌ Platform-specific issues
- ❌ More complex setup

**Recommendation**: Use for specific cases where Docker overhead matters.

## Implementation Plan

### Step 1: MCP Client Library
```python
# lib/mcp_client.py
class MCPClient:
    def __init__(self, config):
        # Start MCP server process
        self.process = subprocess.Popen(...)
    
    def list_tools(self):
        # Send JSON-RPC: tools/list
        return [...]
    
    def call_tool(self, name, arguments):
        # Send JSON-RPC: tools/call
        return result
```

### Step 2: MCP Tool Adapter
```python
# lib/mcp_adapter.py
class MCPToolAdapter:
    def __init__(self, mcp_client, tool_info):
        self.client = mcp_client
        self.tool_info = tool_info
    
    def to_schema(self):
        # Convert MCP tool to our ToolSchema format
        return ToolSchema(
            name=f"mcp.{server}.{tool.name}",
            description=tool.description,
            parameters=tool.inputSchema,
            ...
        )
```

### Step 3: Enhanced Tool Registry
```python
# Extend lib/tool_schema.py
class ToolRegistry:
    def __init__(self, skills_dir, mcp_config=None):
        self.local_tools = discover_local_tools(skills_dir)
        self.mcp_tools = discover_mcp_tools(mcp_config) if mcp_config else {}
        self.tools = {**self.local_tools, **self.mcp_tools}
```

### Step 4: Configuration
```python
# Add to config/cloud.env
MCP_SERVERS_CONFIG="/home/boss/jarvis-voice/config/mcp-servers.json"
MCP_ENABLED=true
```

## Available MCP Servers (Examples)

| Server | Docker Image | Tools | Use Case |
|--------|-------------|-------|----------|
| DuckDuckGo | `mcp/duckduckgo` | search, fetch_content | Web search |
| Filesystem | `mcp/filesystem` | read, write, list | File operations |
| GitHub | `mcp/github` | search_repos, create_issue | GitHub integration |
| Postgres | `mcp/postgres` | query, execute | Database access |
| Brave Search | `mcp/brave-search` | search | Web search (paid API) |

## Next Steps

1. **Test Docker MCP locally**:
   ```bash
   docker pull mcp/duckduckgo
   echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
     docker run -i --rm mcp/duckduckgo
   ```

2. **Implement MCP client** (`lib/mcp_client.py`)

3. **Extend tool registry** (add MCP discovery)

4. **Create MCP config** (`config/mcp-servers.json`)

5. **Test with DuckDuckGo** (voice: "Search for bitcoin news")

## Security Considerations

### Docker MCP
- ✅ Isolated by default
- ⚠️ Mounting volumes gives file access
- ⚠️ `--network host` gives network access
- 💡 Use specific volume mounts, not full filesystem

### Native MCP
- ⚠️ Full system access
- ⚠️ Can execute arbitrary code
- 💡 Review MCP server code before using

### Best Practices
1. Only use trusted MCP servers
2. Review permissions before enabling
3. Use Docker for untrusted servers
4. Monitor logs for unusual activity
5. Disable unused servers

## Performance Considerations

### Startup Time
- **Docker**: ~100-500ms to start container
- **Native**: ~10-50ms
- **Solution**: Keep containers running, reuse connections

### Execution Time
- **Docker**: +50-100ms overhead per call
- **Native**: Minimal overhead
- **Solution**: Acceptable for most use cases

### Memory
- **Docker**: ~50-100MB per container
- **Native**: ~10-30MB per process
- **Solution**: Stop unused servers

## Roadmap

### Phase 1 (MVP)
- [x] Design MCP integration architecture
- [ ] Implement MCP client (Docker support)
- [ ] Extend tool registry for MCP tools
- [ ] Test with DuckDuckGo MCP server

### Phase 2
- [ ] Add native MCP server support (npm)
- [ ] Connection pooling (reuse servers)
- [ ] Auto-restart on crashes

### Phase 3
- [ ] MCP server marketplace
- [ ] One-command install: `jarvis add-mcp duckduckgo`
- [ ] MCP server monitoring dashboard

---

**MCP integration will make Jarvis infinitely extensible!** 🚀

