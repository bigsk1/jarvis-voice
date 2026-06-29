# MCP Remote Transport Support

This document explains how to configure MCP servers using remote transports (SSE and Streamable HTTP).

## Overview

Jarvis now supports three MCP transport types:

| Transport | Description | Use Case |
|-----------|-------------|----------|
| **stdio** | Local subprocess with stdin/stdout | Local CLI tools, Docker containers |
| **sse** | Server-Sent Events over HTTP | Legacy remote servers |
| **http** | Streamable HTTP (recommended) | Modern remote MCP servers |

## Configuration

### Stdio Transport (existing)

```json
{
  "mcpServers": {
    "brave_search": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/brave-search"],
      "env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"},
      "enabled": true
    }
  }
}
```

### Streamable HTTP Transport (recommended for remote servers)

```json
{
  "mcpServers": {
    "coingecko": {
      "type": "http",
      "url": "https://mcp.api.coingecko.com/mcp",
      "description": "Cryptocurrency prices from CoinGecko",
      "enabled": true
    }
  }
}
```

### SSE Transport (for legacy remote servers)

```json
{
  "mcpServers": {
    "legacy_server": {
      "type": "sse",
      "url": "https://example.com/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      },
      "enabled": true
    }
  }
}
```

## Configuration Options

### Stdio Transport
- `command` (required): Executable to run
- `args` (optional): Array of command arguments
- `env` (optional): Environment variables (supports `${VAR}` substitution)
- `enabled` (optional): Enable/disable the server (default: true)

### HTTP/SSE Transport
- `type` (required): `"http"` or `"sse"`
- `url` (required): Server endpoint URL
- `headers` (optional): HTTP headers (supports `${VAR}` substitution)
- `enabled` (optional): Enable/disable the server (default: true)

## Streamable HTTP Protocol

The Streamable HTTP transport follows the MCP specification:

1. **Initialize**: Client sends initialize request WITHOUT session ID
2. **Session ID**: Server returns `Mcp-Session-Id` header
3. **Subsequent Requests**: Client includes `Mcp-Session-Id` header
4. **Response Format**: Server may return JSON or SSE stream

```
Client                                 Server
  |                                      |
  |-- POST initialize (no session) ----->|
  |<-- 200 + Mcp-Session-Id header ------|
  |                                      |
  |-- POST tools/list (with session) --->|
  |<-- 200 SSE stream with tools --------|
  |                                      |
  |-- POST tools/call (with session) --->|
  |<-- 200 SSE stream with result -------|
```

## Available Remote MCP Servers

### CoinGecko
- **URL**: `https://mcp.api.coingecko.com/mcp`
- **Transport**: Streamable HTTP
- **Tools**: 47+ cryptocurrency data tools
- **Features**: Real-time prices, market data, token info

Example config:
```json
"coingecko": {
  "type": "http",
  "url": "https://mcp.api.coingecko.com/mcp",
  "description": "Cryptocurrency data from CoinGecko",
  "enabled": true
}
```

## Security Model

### ✅ Least Privilege (Same as Stdio Transport)

Remote MCP servers follow the **same security model** as local stdio servers:

1. **Only explicit headers are sent** - No `os.environ` is ever passed wholesale
2. **Variable substitution is scoped** - Only substitutes values for explicitly defined headers
3. **Empty by default** - If no `headers` is defined, no sensitive data is sent

### Example: Secure Configuration

```json
"my_server": {
  "type": "http",
  "url": "https://api.example.com/mcp",
  "headers": {
    "Authorization": "Bearer ${MY_API_KEY}"
  }
}
```

**What happens:**
- ✅ Only `MY_API_KEY` is read from environment
- ✅ Only the `Authorization` header is sent
- ❌ `SSH_AUTH_SOCK`, `AWS_SECRET_KEY`, etc. are **NOT exposed**

### ⚠️ What NOT to Do

```json
// DON'T do this (but it's not possible anyway)
"headers": "${ALL_ENV_VARS}"  // Won't work - not supported
```

The client only processes explicitly defined key-value pairs in the `headers` object.

### Security Audit

Before enabling any remote MCP server, audit it:

```bash
./bin/test-mcp --discover | grep dangerous_keywords
```

See: `docs/mcp/MCP_SECURITY_AUDIT.md`

## Environment Variable Substitution

Headers support `${VAR}` syntax to reference environment variables:

```json
{
  "headers": {
    "Authorization": "Bearer ${MY_API_KEY}",
    "X-Custom-Header": "${CUSTOM_VALUE}"
  }
}
```

Variables are resolved from:
1. Process environment (`os.environ`)
2. Config files (`config/cloud.env` or `config/local.env`)

**SECURITY NOTE**: Only the specific variables you reference are read - the entire environment is never exposed.

## Debugging

Enable debug logging with:
```bash
export MCP_DEBUG=1
```

This shows:
- HTTP requests/responses
- Session ID management
- SSE event parsing

## Troubleshooting

### "Session ID required" error
The server requires session management. Make sure you're using `type: "http"` transport.

### "Not Acceptable" error
The server requires specific Accept headers. The client automatically sends:
```
Accept: application/json, text/event-stream
```

### Connection timeout
- Check the URL is correct
- Verify the server is running
- Try increasing timeout in `mcp_client.py`

## See Also

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [MCP for Beginners - HTTP Streaming](https://github.com/microsoft/mcp-for-beginners/blob/main/03-GettingStarted/06-http-streaming/README.md)
- `docs/mcp/MCP_QUICKSTART.md` - General MCP setup guide
