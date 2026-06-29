# MCP Server Security Audit Guide

## Overview

Before enabling any MCP server in Jarvis, **always audit what tools it exposes**. This prevents malicious or poorly-designed MCP servers from:
- Executing arbitrary commands on your system
- Reading sensitive files (.ssh keys, passwords, etc.)
- Making unauthorized network requests
- Deleting or modifying files

---

## Quick Security Audit (3 Steps)

### Step 1: List Configured Servers

```bash
./bin/test-mcp --list
```

**Check:**
- Is the server enabled?
- What environment variables does it need?
- Is the description clear and trustworthy?

### Step 2: Discover Tools (Safe Inspection)

```bash
./bin/test-mcp --discover
```

**This is SAFE** - it only shows what tools exist, doesn't execute anything.

### Step 3: Audit for Dangerous Capabilities

```bash
./bin/test-mcp --discover | grep -E "(execute|command|bash|file|ssh|write|delete|script|code)"
```

**Look for:**
- Tool names with dangerous keywords
- Parameters that accept code/commands
- Descriptions mentioning "executes" or "runs"

---

## Real-World Example: Brave Search (SAFE)

```bash
$ ./bin/test-mcp --discover
```

**Result:**
```
🔧 brave-search (6 tools)
  Tool: mcp_brave-search_brave_web_search
  Description: Performs web searches using the Brave Search API
  Parameters:
    • query (string) (required): Search query
    • count (integer) (optional): Number of results
```

**Security Analysis:**
- ✅ No file system access
- ✅ No command execution
- ✅ Only searches web via API
- ✅ Parameters are safe (query strings, numbers)
- ✅ No sensitive data exposure

**Verdict:** **SAFE TO ENABLE**

---

## Example: Dangerous MCP Server (DO NOT USE)

```
⚠️  Hypothetical malicious server:

Tool: execute_bash_command
Description: Executes arbitrary bash commands on the host system
Parameters:
  • command (string) (required): Bash command to execute
  • sudo (boolean) (optional): Run with sudo privileges
```

**Security Analysis:**
- ❌ Executes arbitrary commands
- ❌ Can access entire filesystem
- ❌ Sudo flag allows privilege escalation
- ❌ No sandboxing or restrictions

**Verdict:** **EXTREMELY DANGEROUS - DO NOT ENABLE**

---

## Red Flags Checklist

### 🚩 Tool Names to Avoid:
- `execute_command`
- `run_bash` / `run_shell`
- `write_file` / `delete_file`
- `read_ssh_key` / `read_credentials`
- `eval_code` / `exec_python`
- `system_command`

### 🚩 Parameter Names to Avoid:
- `command`
- `code` / `script`
- `filepath` / `path` / `directory`
- `sql` / `query` (if database access)
- `url` (if makes arbitrary HTTP requests)

### 🚩 Description Keywords:
- "executes commands"
- "runs code"
- "accesses filesystem"
- "modifies files"
- "requires root"
- "sudo access"

---

## Safe MCP Server Patterns

### ✅ Web Search (Read-Only APIs)
```json
{
  "name": "brave_web_search",
  "description": "Searches the web using Brave API",
  "parameters": {
    "query": "string",
    "count": "integer"
  }
}
```
**Why Safe:** Only reads public data via API, no system access.

### ✅ HTTP Fetch (URL Fetching)
```json
{
  "name": "fetch",
  "description": "Fetches a URL and extracts content",
  "parameters": {
    "url": "string",
    "max_length": "integer"
  }
}
```
**Why Safe:** Only reads public web pages, no file system access.

### ✅ Weather API (External Service)
```json
{
  "name": "get_weather",
  "description": "Gets weather data from API",
  "parameters": {
    "location": "string",
    "units": "string"
  }
}
```
**Why Safe:** Only queries external API, no local system access.

---

## Risky But Acceptable (With Caution)

### ⚠️ File Reader (Limited Scope)
```json
{
  "name": "read_project_file",
  "description": "Reads files ONLY from workspace directory",
  "parameters": {
    "filename": "string"  // Sandboxed to ~/jarvis-workspace
  }
}
```
**Use If:**
- Sandboxed to specific directory
- No write access
- Can't read system files (.ssh, /etc)

### ⚠️ Database Query (Read-Only)
```json
{
  "name": "query_database",
  "description": "Executes READ-ONLY SQL queries",
  "parameters": {
    "query": "string"  // Must be SELECT only
  }
}
```
**Use If:**
- Read-only (no INSERT/UPDATE/DELETE)
- Limited to specific database
- No access to sensitive tables

---

## Testing Workflow

### 1. Add to `mcp-servers.json` (Disabled)

```json
{
  "mcpServers": {
    "new-server": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/new-server"],
      "description": "Unknown server - needs security audit",
      "enabled": false  // Start disabled!
    }
  }
}
```

### 2. Enable Temporarily for Testing

```json
"enabled": true
```

### 3. Audit Tools

```bash
./bin/test-mcp --discover | grep new-server
```

### 4. Test Safely

```bash
./bin/test-mcp --test new-server tool_name '{"param": "safe-value"}'
```

### 5. Enable in Production (If Safe)

Keep `"enabled": true` after audit passes.

---

## Environment Variable Security

### ✅ Explicit Variables (Secure)

```json
"env": {
  "BRAVE_API_KEY": "${BRAVE_API_KEY}"  // Only this var is passed
}
```

**Why Safe:** Server only gets what it needs, not your entire environment.

### ✅ Args Expansion (Secure)

```json
"args": [
  "--proxy-server", "${LOCAL_PROXY}",  // Expanded to CLI arg, NOT env var
  "--api-key", "${MY_API_KEY}"
]
```

**Why Safe:** Values become command-line arguments, not container environment. The MCP server cannot enumerate other env vars - it only sees the final value in the arg string.

**Jarvis proxy note:** Chromium accepts one `--proxy-server` URL. Use `LOCAL_PROXY` there; optional `LOCAL_PROXY2` is for the Python/HTTP client chain (see `docs/NETWORK_PROXY.md`), not a second MCP expansion.

### ✅ Empty Env (Still Secure!)

```json
"env": {}  // Or omit "env" entirely
```

**Why Safe:** Jarvis passes **ZERO** environment variables by default (least privilege).

### ❌ OLD INSECURE WAY (Not used in Jarvis)

```python
# NEVER DO THIS (Jarvis doesn't do this)
env = {**os.environ}  # Passes ALL env vars including secrets!
```

---

## Real Security Audit: Brave Search

```bash
$ ./bin/test-mcp --list
```

```
✅ brave-search (ENABLED)
   Description: Search the web using Brave Search
   Environment: None (secure by default)
```

```bash
$ ./bin/test-mcp --discover
```

**All 6 Tools:**
- `brave_web_search` - Web search
- `brave_local_search` - Local businesses (requires Pro API)
- `brave_video_search` - Video search
- `brave_image_search` - Image search
- `brave_news_search` - News articles
- `brave_summarizer` - AI summaries (requires Pro API)

**Security Audit:**
```bash
$ ./bin/test-mcp --discover | grep -E "(execute|command|bash|file|ssh|write|delete)"
# No matches found ✅
```

**Parameters Audit:**
- All parameters are safe (query strings, integers, booleans)
- No `command`, `code`, or `filepath` parameters
- No system-level access

**Verdict:** ✅ **SAFE TO USE IN PRODUCTION**

---

## When to Disable an MCP Server

Immediately disable and investigate if you see:

1. **Tool names with dangerous keywords**
   - `execute_`, `run_`, `eval_`, `bash_`, `shell_`

2. **Parameters accepting code**
   - `command`, `code`, `script`, `sql` (if not read-only)

3. **File system access**
   - `read_file`, `write_file`, `delete_file`
   - Parameters named `path`, `filepath`, `directory`

4. **Network access to internal systems**
   - Parameters accepting arbitrary URLs
   - Access to `localhost`, `127.0.0.1`, `192.168.*`

5. **Credential access**
   - Reading `.ssh`, `.aws`, `.env` files
   - Parameters named `password`, `token`, `key`

---

## Summary

**Before enabling ANY MCP server:**

1. ✅ Run `./bin/test-mcp --list` - Check server config
2. ✅ Run `./bin/test-mcp --discover` - See all tools
3. ✅ Audit for dangerous keywords - `grep` for red flags
4. ✅ Test individually - `--test` with safe parameters
5. ✅ Enable in production - Only if audit passes

**Default stance:** Treat all unknown MCP servers as **untrusted** until proven safe.

---

## Additional Resources

- Main README: `~/jarvis-voice/README.md`
- Config Guide: `~/jarvis-voice/config/README.md`
- MCP Quickstart: `~/jarvis-voice/docs/mcp/MCP_QUICKSTART.md`
- Test Script: `~/jarvis-voice/bin/test-mcp`
