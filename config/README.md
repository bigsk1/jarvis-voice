# Jarvis Configuration

This directory contains configuration files for Jarvis Voice Assistant.

## Quick Start

1. **Choose your mode:**
   - **Cloud mode**: xAI, Anthropic, OpenAI, or Ollama Cloud through a signed-in daemon or `OLLAMA_API_KEY`
   - **Local mode**: Ollama on your GPU (offline-capable; no cloud LLM keys required)

2. **Copy the example file:**
   ```bash
   # For cloud mode (full multi-provider template):
   cp cloud.env.example cloud.env

   # For cloud mode with OpenAI as the primary provider:
   cp cloud.openai.env.example cloud.env

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

   # Full service stack / Web UIs
   ./bin/start                 # cloud.env (default)
   ./bin/start --local         # local.env
   ./bin/start --ui-only --local
   ```

5. **(Optional) Configure MCP servers:**
   - MCP servers add tools such as web search, HTTP fetch, and other integrations.
   - Edit `config/mcp-servers.json` to enable or disable servers.
   - See [MCP Server Configuration](#mcp-server-configuration), [Tool RAG implementation summary](../docs/archive/TOOL_RAG_IMPLEMENTATION_SUMMARY.md) (historical), and [MCP remote transport](../docs/mcp/MCP_REMOTE_TRANSPORT.md).
   - After changing MCP servers or tools, re-sync the tools database: `./bin/sync-tools.py cloud` or `./bin/sync-tools.py local`.

## Configuration Files

Copy the template for each mode you intend to run (both live filenames are
gitignored, but a one-mode-only install needs only its selected file):

```bash
cp cloud.env.example cloud.env    # cloud mode (all providers)
cp cloud.openai.env.example cloud.env   # cloud mode, OpenAI primary provider
cp local.env.example local.env    # local mode
```

| File | Role |
|------|------|
| `cloud.env.example` / `local.env.example` | Committed templates — safe to browse in git |
| `cloud.openai.env.example` | Concise OpenAI-primary template (one required secret plus optional tool placeholders) |
| `cloud.env` / `local.env` | Your machine-specific settings and secrets (not committed) |
| `mcp-servers.json` | Jarvis MCP server definitions (committed; no secrets in git) |

### Startup env mode

Top-level launchers resolve startup mode in this order: explicit CLI selection,
the process `JARVIS_MODE`, then the backward-compatible `cloud` default. Valid
values are only `cloud` and `local`; provider/model settings do not choose the
startup env file.

Native launchers never parse the repo-root `.env`. That file is reserved for
Docker Compose interpolation, which injects `JARVIS_MODE` into containers.
Memory, Intelligence, Docs Assistant, and Web chat retain their independent
request/browser data or LLM mode selectors after startup.

### `cloud.env` (Cloud Mode)

- **LLM providers**: xAI, Anthropic, OpenAI, or Ollama Cloud via `LLM_PROVIDER`
- **Also configures**: cloud TTS/STT, image/video APIs, embeddings, and optional paid services
- **Best for**: production use, complex tool calling, providers with large context windows
- **OpenCode**: can use the same cloud providers (Anthropic or OpenAI recommended for coding tasks)

See also: [xAI provider guide](../docs/XAI_PROVIDER.md),
[Ollama local/cloud guide](../docs/ollama/README.md), and
[Speech-to-Text guide](../docs/SPEECH_TO_TEXT.md).

### `cloud.openai.env.example` (OpenAI primary provider)

Concise cloud template for users with **one required OpenAI API key**. It keeps
chat, STT, TTS, embeddings, image/video tools, and Responses routing on OpenAI.
The OpenAI core is grouped at the top; optional tool APIs and self-hosted
integration settings remain available in a separate section at the bottom.
For the simplest one-key tool surface, uncomment
`JARVIS_TOOL_PROFILE=openai_only`; this keeps OpenAI-backed and
credential-free tools while hiding integrations that need additional setup.

```bash
cp cloud.openai.env.example cloud.env
# Set OPENAI_API_KEY, then:
./bin/sync-tools.py cloud
./bin/manage-tools.py --mode cloud list
```

Tools that need other API keys, OAuth caches, webhooks, or self-hosted URLs
(SerpApi, Brave, Spotify, Crawl4AI, email webhooks, etc.) stay **unavailable**
through manifest availability checks or the template's `BLOCKED_TOOLS` default.
After configuring a blocklisted integration, remove its tool name from that
list and re-run `./bin/sync-tools.py cloud`. See `skills/README.md`.

### `local.env` (Local Mode)

- **Uses**: Ollama with local models (`gemma4`, `qwen3.5:latest`, etc.; see `local.env.example`)
- **Requires**: GPU with enough VRAM for your chosen model and context window
- **Best for**: offline work, privacy, avoiding per-request LLM fees
- **OpenCode**: local Ollama or a cloud provider (cloud is usually more reliable for autonomous coding)

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

For Anthropic, audit the curated catalog against the Models API before and after an update:

```bash
./bin/audit-anthropic-models.py --mode cloud
./bin/audit-anthropic-models.py --mode cloud --json
```

The selected mode controls which env file supplies `ANTHROPIC_API_KEY`; use `--mode local` when the key exists only in `config/local.env`. The audit is read-only and never rewrites the catalog. It checks model availability, canonical IDs, input/output token limits, and the complete capabilities object. Anthropic's Models API does not return pricing, so catalog prices retain a manual verification date, source URL, and optional validity deadline; stale or expired verification is reported as a warning.

xAI has a parallel read-only audit that merges its basic and rich language-model endpoints:

```bash
./bin/audit-xai-models.py --mode cloud
./bin/audit-xai-models.py --mode cloud --json
```

This validates canonical IDs, accepted aliases, context windows, input/output modalities, standard pricing, and long-context pricing tiers. xAI's API does not expose every marketing-level capability (for example, configurable reasoning), so those flags remain curated in `lib/model_catalog.py`. Models intentionally unsuitable for the current Jarvis integration are listed explicitly by the audit instead of being silently ignored.

OpenAI's Models API has a narrower identity-and-availability schema:

```bash
./bin/audit-openai-models.py --mode cloud
./bin/audit-openai-models.py --mode cloud --json
./bin/audit-openai-models.py --mode cloud --show-all
```

The audit verifies that curated IDs or aliases are available to the selected API key and conservatively flags only newer general-purpose GPT families for review. Specialized image, audio, realtime, embedding, moderation, Sora, search, Codex, and legacy models remain visible in JSON/`--show-all` output without being misclassified as missing chat options. OpenAI's endpoint does not return context limits, capabilities, modalities, or pricing, so those fields remain manually curated and must be verified against their dedicated official documentation before adding a surfaced model.

When removing an old curated cloud chat model:
1. Remove it from `lib/model_catalog.py`
2. Clean up docs/examples that still mention it
3. Keep or remove any fallback pricing in `lib/cost_estimator.py` depending on whether you still want historical/specialized cost estimation support

Notes:
- Ollama models are not curated here; they are still discovered/configured dynamically
- Image/video provider models are still managed in their existing provider-specific code paths

**Jarvis tool calling** (main LLM):

```bash
# Cloud mode — pick one provider
LLM_PROVIDER="xai"
XAI_MODEL="grok-4.6"

# LLM_PROVIDER="anthropic"
# ANTHROPIC_MODEL="claude-sonnet-5"

# LLM_PROVIDER="openai"
# OPENAI_MODEL="gpt-5.4-mini"

# LLM_PROVIDER="ollama"
# OLLAMA_BASE_URL="http://your-signed-in-ollama-host:11434"
# OLLAMA_CLOUD_MODEL="minimax-m3:cloud"
# Or set OLLAMA_API_KEY and use a canonical ID returned by ollama.com/api/tags.

# Local mode
LLM_PROVIDER="ollama"
OLLAMA_MODEL="gemma4"
ALLOW_OLLAMA_CLOUD=false  # true permits signed-daemon :cloud cards locally
```

**OpenCode Agent** (coding tasks):
```bash
# Recommended default for the OpenCode web UI and Jarvis tool
OPENCODE_PROVIDER="xai"
OPENCODE_MODEL="grok-build-0.1"

# Other cloud options
# OPENCODE_PROVIDER="anthropic"
# OPENCODE_MODEL="claude-sonnet-4-5-20250929"
# OPENCODE_PROVIDER="openai"
# OPENCODE_MODEL="gpt-5.4-mini"

# Experimental: Local Ollama models (less safe, less reliable)
OPENCODE_PROVIDER="ollama"
OPENCODE_MODEL="gemma4"
```

### Response Style

```bash
JARVIS_RESPONSE_STYLE="auto"  # Recommended
# Options:
#   "auto" - Smart formatting based on context
#   "casual" - Always concise (8-12 words for voice)
#   "detailed" - Full LLM output (debugging)
```

### Optional HTTP proxy

For networks that require an HTTP(S) proxy for outbound API calls and downloads, configure `LOCAL_PROXY` and optionally `LOCAL_PROXY2` in `cloud.env` / `local.env`. See **[Network proxy (`LOCAL_PROXY` / `LOCAL_PROXY2`)](../docs/NETWORK_PROXY.md)** for behavior, tool coverage, and MCP limitations.

## Security Notes

1. Keep secrets in `cloud.env` / `local.env` only — both are listed in `.gitignore`.
2. **OpenCode**: local models can execute arbitrary code; many setups use a cloud provider for OpenCode even when Jarvis runs locally. Workspace is sandboxed to `~/jarvis-workspace`.

## Troubleshooting

### "OpenCode server not reachable"
```bash
# Start OpenCode
sudo systemctl start opencode-jarvis.service

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

`OLLAMA_BASE_URL` also accepts a comma-separated fallback list like
`"http://192.168.70.226:11434,http://192.168.1.68:11434"`. Local mode retains
`http://localhost:11434` as a final compatibility fallback. Cloud mode tries
only explicitly listed hosts, so add localhost yourself only when intentional.

### GPU Optimization
```bash
# Local models only: adjust for your VRAM (16GB example).
# Cloud-backed Ollama models ignore this Jarvis setting.
OLLAMA_CONTEXT_WINDOW=12888
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
# Use Ollama for Jarvis, a cloud provider for OpenCode
LLM_PROVIDER="ollama"  # Free, offline
OPENCODE_PROVIDER="xai"  # Paid, coding-oriented Grok model
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

**Security Note**: If you omit the `"env"` key or use `"env": {}`, **no
ordinary environment variables** are passed to the MCP server. This is secure
by default—the server won't have access to your API keys or secrets. An
explicit `proxy_policy: "prefer"` or `"require"` permits only the conventional
proxy names Jarvis derives from `LOCAL_PROXY` / `LOCAL_PROXY2`; it does not
broaden the allowlist or pass the source variable names.

### Proxy Policy

Both native `*.tool.json` files and MCP server entries support top-level
`proxy_policy` runtime metadata, but Jarvis applies it differently for the two
execution paths.

The policy values express the same intent in both places:

- Omitted / `"inherit"` preserves existing behavior.
- `"off"` forces direct networking.
- `"prefer"` uses `LOCAL_PROXY`, then `LOCAL_PROXY2`, with direct fallback.
- `"require"` uses the proxy chain and fails closed without a direct fallback.

#### MCP server entries: automatic proxy environment

For an MCP server, setting `"proxy_policy": "prefer"` or `"require"` is the
Jarvis-side configuration needed to use `LOCAL_PROXY` / `LOCAL_PROXY2`. Jarvis
selects the first reachable proxy listener and launches the server with derived
`HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` variables (plus lowercase
equivalents). Docker MCP servers receive those names through explicit
`docker run -e` arguments.

The MCP server's HTTP client must honor these conventional proxy variables.
Most standard clients do, but a server that ignores them needs its own
server-specific proxy configuration. A TLS-intercepting proxy may also require
the server to trust its CA certificate.

#### Native `*.tool.json` manifests: policy delivered to tool code

For a native tool, the manifest policy is passed to the subprocess as
`JARVIS_TOOL_PROXY_POLICY`. `"off"` also strips Jarvis and conventional proxy
variables, but `"prefer"` and `"require"` do not transparently reroute arbitrary
socket or third-party-library traffic.

The native tool must use Jarvis's proxy-aware helpers in `lib/http_client.py`
(or implement equivalent policy-aware logic). Tools already using helpers such
as `http_request()`, `build_proxy_url_attempts()`, or
`proxy_policy_allows_direct_fallback()` need no additional per-tool wiring;
adding the manifest field alone is not sufficient for unrelated networking
code.

See [`docs/NETWORK_PROXY.md`](../docs/NETWORK_PROXY.md) for the complete
transport behavior and current tool coverage.

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
- `${VAR_NAME}` is replaced with the value from the active mode's `.env` file
  at runtime, including request-local Web UI cloud/local scopes
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

**📖 For detailed security audit guide, see:** [`docs/mcp/MCP_SECURITY_AUDIT.md`](../docs/mcp/MCP_SECURITY_AUDIT.md)

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

### Cloud Mode

- **xAI**: `grok-4.6` (default), `grok-4.5`, `grok-4.3`, `grok-build-0.1` (see `cloud.env.example` and [xAI provider](../docs/XAI_PROVIDER.md))
- **Anthropic**: `claude-sonnet-5` and related Claude models
- **OpenAI**: `gpt-5.4-mini`, `gpt-5.4-nano`, and related GPT models
- **Ollama Cloud**: a cloud-tagged model through a signed-in daemon, or a canonical direct-API model with `OLLAMA_API_KEY`

Curated metadata for the Web UI and cost helpers lives in `lib/model_catalog.py`.

### Local Mode (Ollama)

- **Jarvis**: `gemma4`, `qwen3.5:latest`, or another tool-capable model you have pulled
- Set `ALLOW_OLLAMA_CLOUD=true` to additionally permit signed-daemon cloud cards; direct API keys remain cloud-mode-only
- **OpenCode**: prefer a cloud API for reliability; local Ollama is supported but less dependable for long coding runs

## Quick Reference

**Configuration Files:**
- `cloud.env` / `local.env` - Main config (API keys, settings)
- `mcp-servers.json` - MCP server configuration (Jarvis)
- `config/opencode.config.json.template` - Git-safe OpenCode config example for new installs
- `~/.config/opencode/opencode.json` - Live OpenCode config (copy from the template and customize)

**Key Concepts:**
- API keys go in `.env` files
- MCP servers can reference `.env` variables via `${VAR_NAME}`
- **Security**: Only explicitly listed `env` vars are passed (least privilege)
- Jarvis and OpenCode have separate MCP configurations

**Testing MCP Servers:**
```bash
./bin/test-mcp --list       # List all servers (enabled/disabled)
./bin/test-mcp --discover   # Discover tools (SAFE inspection)
./bin/test-mcp --all         # Full overview (list + discover)
```

## Related docs

- [Main README](../README.md)
- [Install guide](../docs/INSTALL_GUIDE.md)
- [xAI provider](../docs/XAI_PROVIDER.md)
- [MCP security audit](../docs/mcp/MCP_SECURITY_AUDIT.md)
- [MCP quickstart](../docs/mcp/MCP_QUICKSTART.md)
- [Documentation index](../docs/README.md)
