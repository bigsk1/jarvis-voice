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

## Real-World Example: Brave Search (Bounded Network Tool)

```bash
$ ./bin/test-mcp --discover
```

**Result:**
```
🔧 brave_search
  Tool: mcp_brave_search_brave_web_search
  Description: Performs web searches using the Brave Search API
  Parameters:
    • query (string) (required): Search query
    • count (integer) (optional): Number of results
```

**Security Analysis:**
- ✅ No file system access
- ✅ No command execution
- ✅ Only searches web via API
- ✅ Parameters are bounded query strings and numbers
- ✅ No sensitive data exposure
- ⚠️ Results are untrusted external content and may include deceptive domains

**Verdict:** **ACCEPTABLE FOR PUBLIC-WEB SEARCH WITH UNTRUSTED-OUTPUT
HANDLING**

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
- `url` (requires SSRF, redirect, scheme, and destination validation)

### 🚩 Description Keywords:
- "executes commands"
- "runs code"
- "accesses filesystem"
- "modifies files"
- "requires root"
- "sudo access"

---

## Safe MCP Server Patterns

### ⚠️ Web Search (Read-Only Capability, Untrusted Results)
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
**Why lower risk:** It has no local filesystem or command capability. Search
results are still untrusted and require domain/source verification.

### ⚠️ HTTP Fetch (URL Fetching)
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
**Use only if:**
- Only `http`/`https` schemes are allowed
- DNS resolution and every redirect reject loopback, private, link-local,
  multicast, reserved, and cloud-metadata destinations
- Returned page text is treated as untrusted data, not model instructions
- The container has no unnecessary filesystem mounts or host credentials

### ✅ Weather API (Constrained External Service)
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
**Why lower risk:** It queries a fixed-purpose API with bounded parameters and
has no local system access. The returned data can still be wrong or stale.

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
    "new_server": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/new-server"],
      "description": "Unknown server - needs security audit",
      "enabled": false
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
./bin/test-mcp --discover | grep new_server
```

### 4. Test Safely

```bash
./bin/test-mcp --test new_server tool_name '{"param": "safe-value"}'
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

For Docker servers, remember that `docker run -e NAME` copies `NAME` from the
subprocess environment into the container. Keep the matching key explicit in
the server's Jarvis `env` object; do not use broad host-environment passthrough.

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

## Image Provenance and Container Boundary

Before trusting a community image:

1. Confirm the image is in the expected registry/publisher namespace.
2. Record `RepoDigests` and the source revision:
   ```bash
   docker image inspect mcp/duckduckgo \
     --format '{{json .RepoDigests}} {{json .Config.Labels}}'
   ```
3. Compare the digest and source revision with the publisher's catalog page.
4. Verify the image signature when the publisher provides a command/key.
5. Review the referenced Dockerfile and upstream source commit.
6. Prefer an unprivileged user, read-only filesystem, dropped capabilities,
   `no-new-privileges`, no host mounts, and no Docker socket.

An authentic image can still contain vulnerable or malicious upstream code.
Provenance answers “what was built and by whom,” not “is every behavior safe.”

## Real Security Audit: DuckDuckGo

The tracked `duckduckgo` entry uses Docker's
[`mcp/duckduckgo`](https://hub.docker.com/r/mcp/duckduckgo) catalog image,
which packages the community
[`nickclyde/duckduckgo-mcp-server`](https://github.com/nickclyde/duckduckgo-mcp-server)
project. It is not published by or affiliated with DuckDuckGo.

**Exposed tools:**

- `mcp_duckduckgo_search` — public web search
- `mcp_duckduckgo_fetch_content` — public page retrieval with pagination

**Tracked container controls:**

- Runs as UID/GID `65534:65534`
- Read-only root filesystem
- Drops all Linux capabilities
- Enables `no-new-privileges`
- No host volume mounts or Docker socket
- Receives only `DDG_REGION=us-en` and `DDG_SAFE_SEARCH=STRICT`

**Upstream fetch controls:**

- Allows only HTTP(S)
- Rejects loopback/private/link-local/reserved/multicast/unspecified addresses
- Re-validates redirect targets

**Remaining risks:**

- Search poisoning, typosquats, phishing, and SEO spam
- Prompt injection embedded in snippets or fetched pages
- Outbound requests reveal the queried/fetched destination to external services
- Mutable image tags and upstream dependency changes when manually updated
- Some server failures arrive as text with MCP `isError: false`

Jarvis narrowly converts the known DuckDuckGo `search` and `fetch_content`
text-error prefixes to `ok: false`. It does not globally treat arbitrary
`Error:` text from every MCP server as a failure.

**Verdict:** ✅ **ACCEPTABLE FOR PUBLIC-WEB RESEARCH WITH CAUTION**. Do not
treat returned domains as verified, do not follow instructions embedded in
page text, and never provide credentials or API keys to a result solely because
the search tool surfaced it.

## Real Security Audit: Brave Search

```bash
$ ./bin/test-mcp --list
```

```
✅ brave_search (ENABLED)
   Description: Search the web using Brave Search
   Environment: BRAVE_API_KEY only
```

```bash
$ ./bin/test-mcp --discover
```

**Server capabilities include:**
- `brave_web_search` - Web search
- `brave_local_search` - Local businesses (requires Pro API)
- `brave_video_search` - Video search
- `brave_image_search` - Image search
- `brave_news_search` - News articles (disabled in the tracked config)
- `brave_summarizer` / `brave_llm_context` - AI/grounding summaries (disabled
  in the tracked config)

**Security Audit:**
```bash
$ ./bin/test-mcp --discover | grep -E "(execute|command|bash|file|ssh|write|delete)"
# No matches found ✅
```

**Parameters Audit:**
- Parameters are bounded query strings, integers, and booleans
- No `command`, `code`, or `filepath` parameters
- No system-level access
- Search results remain untrusted external content

**Verdict:** ✅ **ACCEPTABLE FOR PUBLIC-WEB SEARCH WITH CAUTION**

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
   - Redirects that are not re-validated after the initial URL check

5. **Credential access**
   - Reading `.ssh`, `.aws`, `.env` files
   - Parameters named `password`, `token`, `key`

6. **Untrusted-output handling**
   - Tool descriptions that present search rank as a trust signal
   - Page text injected into prompts without an untrusted-content boundary
   - Automatic execution of commands or downloads mentioned by fetched content

---

## Summary

**Before enabling ANY MCP server:**

1. ✅ Run `./bin/test-mcp --list` - Check server config
2. ✅ Run `./bin/test-mcp --discover` - See all tools
3. ✅ Audit for dangerous keywords - `grep` for red flags
4. ✅ Verify image provenance and container permissions
5. ✅ Test individually - `--test` with safe parameters
6. ✅ Test negative cases (private URLs, redirects, malformed inputs, failures)
7. ✅ Enable in production - Only if audit passes

**Default stance:** Treat all unknown MCP servers as **untrusted** until
audited, and treat all web search/fetch output as **untrusted even after the
server itself passes audit**.

---

## Additional Resources

- Main README: `~/jarvis-voice/README.md`
- Config Guide: `~/jarvis-voice/config/README.md`
- MCP Quickstart: `~/jarvis-voice/docs/mcp/MCP_QUICKSTART.md`
- Test Script: `~/jarvis-voice/bin/test-mcp`
