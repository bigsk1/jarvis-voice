# Tool Management System

## Overview

Jarvis now supports enabling/disabling tools dynamically, similar to MCP servers. This allows you to:

- **Reduce token count** for local models (important for Ollama)
- **Improve response speed** by loading fewer tools
- **Create focused profiles** (coding tools only, home automation only, etc.)
- **Easier testing** by temporarily disabling tools

## Quick Start

```bash
# List all tools
./bin/manage-tools.py list

# List with descriptions
./bin/manage-tools.py list -v

# Disable a tool
./bin/manage-tools.py disable execute_bash

# Enable a tool
./bin/manage-tools.py enable execute_bash

# Enable all tools
./bin/manage-tools.py enable-all
```

## How It Works

### Tool Schema Format

Each `*.tool.json` file now has an `enabled` field:

```json
{
  "enabled": true,
  "name": "crypto_price",
  "description": "Get cryptocurrency prices",
  "script": "crypto_price.py",
  "parameters": { ... },
  "permissions": { ... }
}
```

- **`enabled: true`** → Tool loads normally
- **`enabled: false`** → Tool skipped at startup (no memory/token usage)

### Backward Compatibility

- Tools without `enabled` field default to `true`
- All existing tools have been migrated automatically
- No breaking changes to existing code

## Use Cases

### 1. Reduce Token Count for Local Models

Ollama models have limited context windows. Disable unnecessary tools:

```bash
# Keep only essential tools for conversation
./bin/manage-tools.py disable send_webhook
./bin/manage-tools.py disable api_call
./bin/manage-tools.py disable execute_bash
./bin/manage-tools.py disable opencode

# Result: ~6k tokens → ~3k tokens (50% reduction!)
```

### 2. Create Focused Profiles

**Coding Profile** (disable non-coding tools):
```bash
./bin/manage-tools.py disable crypto_price
./bin/manage-tools.py disable send_webhook
# Keep: opencode, execute_bash, memory tools
```

**Home Automation Profile**:
```bash
./bin/manage-tools.py disable opencode
./bin/manage-tools.py disable crypto_price
# Keep: api_call, send_webhook, execute_bash
```

### 3. Testing & Development

```bash
# Disable tools you're not testing
./bin/manage-tools.py disable opencode  # Save 2+ minutes startup time

# Focus on specific tool
./bin/manage-tools.py disable api_call
# ... test other tools ...
./bin/manage-tools.py enable api_call
```

### 4. Security Hardening

```bash
# Disable dangerous tools in production
./bin/manage-tools.py disable execute_bash
./bin/manage-tools.py disable opencode
```

## Implementation Details

### Code Changes

**1. `lib/tool_schema.py`** - Added enable/disable check:
```python
def _discover_tools(self):
    for tool_file in self.skills_dir.glob("*.tool.json"):
        with open(tool_file, 'r') as f:
            tool_config = json.load(f)

        # Check if tool is enabled (defaults to True)
        if not tool_config.get('enabled', True):
            print(f"⊝ Skipping {tool_config.get('name')} (disabled)")
            continue

        schema = ToolSchema.from_json_file(str(tool_file))
        self.tools[schema.name] = schema
```

**2. `bin/manage-tools.py`** - New management utility:
- List tools and status
- Enable/disable individual tools
- Bulk operations
- Color-coded output

**3. All `skills/*.tool.json`** - Added `enabled: true` field

### No Hardcoded Dependencies

✅ No tool names in code (dynamically discovered)
✅ No broken imports if tool disabled
✅ System prompts mention tools as examples only
✅ Safe to add/remove tools anytime

## Token Count Impact

In current Tool RAG runtime, token impact is best measured from the final tool list rather than from all enabled tools. Enable `TOOL_RAG_TRACE_ENABLED=true` and inspect `logs/tool-rag/tool-rag-YYYY-MM-DD.jsonl`; each trace includes `final_tool_count`, `tool_schema_chars`, `tool_schema_est_tokens`, and `tool_schema_top` so you can see which schemas actually reached the LLM.

### Example Reduction (Ollama qwen3.5:latest)

**All 17 tools + 2 MCP servers:**
- Baseline tokens: ~6,200
- With system prompt: ~7,500

**Essential 10 tools only:**
- Baseline tokens: ~3,800 (-39%)
- With system prompt: ~5,100 (-32%)

**Impact:**
- Faster responses (less context to process)
- More room for conversation history
- Less likely to hit context limit

## Best Practices

### 1. Start with Everything Enabled

Get familiar with all tools first:
```bash
./bin/manage-tools.py enable-all
```

### 2. Profile Your Usage

Track which tools you actually use:
```bash
# Check tool usage logs
cat logs/tools/tool-calls-*.jsonl | jq -r '.tool_name' | sort | uniq -c | sort -nr
```

### 3. Disable Rarely Used Tools

```bash
# If you never use crypto prices
./bin/manage-tools.py disable crypto_price

# If you don't use webhooks
./bin/manage-tools.py disable send_webhook
```

### 4. Keep Core Tools Enabled

Always keep these enabled for basic functionality:
- `get_time` - Time/date queries
- `remember` / `recall` / `search_memory` - Memory system
- `get_recent_conversations` - Context awareness

### 5. Document Your Profile

```bash
# Save your enabled tools
./bin/manage-tools.py list > ~/jarvis-voice/skills/profiles/jarvis-tools-profile.txt
```

## Migration (Already Done)

All existing tools have been migrated automatically:

```bash
./bin/manage-tools.py init  # Adds 'enabled': true to all tools
```

Output:
```
✓ Added 'enabled' field to semantic_recall
✓ Added 'enabled' field to search_memory
...
✓ Updated 17 tool(s)
```

## Comparison with MCP Servers

### MCP Servers (`config/mcp-servers.json`)
```json
{
  "mcpServers": {
    "duckduckgo": {
      "command": "docker",
      "enabled": true
    }
  }
}
```

### Local Tools (`skills/*.tool.json`)
```json
{
  "enabled": true,
  "name": "crypto_price",
  "script": "crypto_price.py"
}
```

**Same pattern, consistent experience!**

## Troubleshooting

### Tool Not Loading

```bash
# Check if it's disabled
./bin/manage-tools.py list | grep my_tool

# Enable it
./bin/manage-tools.py enable my_tool
```

### "Tool not found" Error

```bash
# List available tools
./bin/manage-tools.py list

# Check tool file exists
ls -la skills/my_tool.tool.json
```

### Performance Issues with Local Models

```bash
# Check baseline token count
cat logs/baseline-tokens-local.json

# Disable heavy tools
./bin/manage-tools.py disable opencode     # -500 tokens
./bin/manage-tools.py disable execute_bash # -200 tokens
./bin/manage-tools.py disable api_call     # -300 tokens
```

## Future Enhancements

### Profiles (Not Yet Implemented)

```bash
# Save current state as profile
./bin/manage-tools.py save-profile coding

# Load profile
./bin/manage-tools.py load-profile coding
```

### Auto-Detection (Not Yet Implemented)

Automatically disable unused tools after 7 days:
```bash
./bin/manage-tools.py auto-disable --unused-days 7
```

## Summary

✅ **Implemented:**
- Enable/disable field in tool.json
- Tool discovery respects enabled flag
- Management utility (`manage-tools.py`)
- Documentation updated
- All tools migrated

✅ **No Breaking Changes:**
- Backward compatible (defaults to true)
- No hardcoded tool dependencies
- Safe to enable/disable anytime

✅ **Benefits:**
- 30-50% token reduction possible
- Faster responses
- Easier testing
- Better organized tool library

## See Also

- `docs/TOOL_CALLING_SYSTEM.md` - Tool system overview
- `skills/README.md` - Creating custom tools
- `config/mcp-servers.json` - MCP server configuration

---

## Tool Roadmap & Brainstorm

### Current Coverage (78 Tool Manifests)

#### Local Tools by Category

| Category | Tools | Count |
|----------|-------|-------|
| **Memory** | remember, recall, search_memory, semantic_recall, deep_memory_search, forget, update_memory | 7 |
| **Conversations** | get_recent_conversations, search_conversations | 2 |
| **Intelligence** | manage_intel, ingest_intel | 2 |
| **Reminders/Alerts** | create_reminder, list_reminders, acknowledge_reminders, list_alerts, acknowledge_alerts, price_alert | 6 |
| **Development** | opencode, check_opencode_sessions, execute_bash, check_tool_logs, query_service_logs | 5 |
| **Communication** | send_email, send_webhook, phone_call, samantha | 4 |
| **External APIs** | api_call, crypto_price, stock_price, weather, get_time | 5 |
| **Media & Content** | spotify, generate_music, youtube_transcript, crawl_url, screenshot_url | 5 |
| **Image & Vision** | generate_image, analyze_image, upload_cloudflare | 3 |
| **Artifacts** | stash, canvas, pdf_create, pdf_read, printer | 5 |
| **System** | speaker_volume, ssh_remote | 2 |
| **Auto-Tools** | docker_control, network_tools, system_monitor, text_summarizer, status_recap, generate_password | 6 |
| **Utility** | calculator | 1 |

**Total at last verification: 78 `*.tool.json` manifests.** Profile overlays and
per-mode availability can reduce the active set. Recount with:

```bash
find skills -name '*.tool.json' | wc -l
```

#### MCP Servers (4 configured)

| Server | Capability | Status | Notes |
|--------|------------|--------|-------|
| `brave_search` | Web search | ✅ Enabled | Primary search, Pro AI API |
| `fetch` | HTTP GET/POST | ✅ Enabled | URL content retrieval (static HTML) |
| `sequentialthinking` | Deep reasoning | ❌ Disabled | For complex reflection |
| `playwright` | Browser automation | ❌ Disabled | JS-heavy sites, forms, screenshots, PDFs |

---

### Completed Tools (Previously on Roadmap)

These tools from the original roadmap have been implemented:

| Tool | Status | Implementation |
|------|--------|----------------|
| ✅ **weather** | Done 11-29-2025 | Local tool (OpenWeatherMap API) |
| ✅ **calendar** | Done 11-26-2025 | n8n workflows (Google Calendar sync) |
| ✅ **spotify** | Done | Local tool (Spotify Web API) |
| ✅ **stock_price** | Done | Local tool (yfinance - stocks, futures, forex) |
| ✅ **screenshot** | Done | `screenshot_url` - Full page capture with AI vision |
| ✅ **image_generate** | Done | `generate_image` - Gemini 3 Pro with Search Grounding |
| ✅ **pdf_extract** | Done | `pdf_read` - Text extraction, merge, split, search |
| ✅ **youtube_transcript** | Done | `youtube_transcript` - Download video transcripts |

---

### Missing Tools - Priority List

#### 🔴 HIGH PRIORITY (Most Useful)

| Tool | Description | Implementation |
|------|-------------|----------------|
| **slack_message** | Send Slack messages, read channels | n8n workflow (Slack node) |
| **file_search** | Search files by name/content in workspace | Local tool (Python subprocess) |
| **clipboard** | Read/write system clipboard | Local tool (pyperclip) |

#### 🟡 MEDIUM PRIORITY (Nice to Have)

| Tool | Description | Implementation |
|------|-------------|----------------|
| **todoist** | Task management (add, complete, list) | MCP or n8n |
| **youtube_search** | Search YouTube videos | MCP or n8n |
| **github_issues** | Create/list GitHub issues & PRs | MCP: `@modelcontextprotocol/github` |
| **translate** | Language translation | Local tool (googletrans) |
| **rss_feed** | Read RSS/Atom feeds | Local tool (feedparser) |
| **qr_code** | Generate/read QR codes | Local tool (qrcode/pyzbar) |

#### 🟢 LOW PRIORITY (Future Ideas)

| Tool | Description | Implementation |
|------|-------------|----------------|
| **home_assistant** | Smart home control (lights, locks, etc.) | n8n or direct API |
| **mqtt_publish** | IoT device messaging | Local tool (paho-mqtt) |
| **sms_send** | Send SMS via Twilio | n8n workflow |
| **discord_message** | Post to Discord channels | n8n workflow |
| **maps_directions** | Get directions, travel time | n8n (Google Maps node) |
| **linear_issues** | Linear.app issue tracking | MCP: `@anthropics/linear-mcp` |
| **notion** | Notion page read/write | MCP or n8n |

> **Note:** OCR is handled by `analyze_image` tool which can extract text from images via vision models.

---

### Implementation Guide

#### Option 1: Local Tool (Python Script)
Best for: Simple, fast, no external dependencies

```bash
# Create tool files
touch skills/weather.py skills/weather.tool.json

# Template
./bin/manage-tools.py template weather
```

**Pros:** Fast, no network latency, full control
**Cons:** Must implement yourself, maintain code

#### Option 2: MCP Server (Docker/npx)
Best for: Complex tools, community-maintained

```json
// config/mcp-servers.json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "..." }
    }
  }
}
```

**Available MCP Servers:**
- `@modelcontextprotocol/server-github` - GitHub integration
- `@modelcontextprotocol/server-slack` - Slack integration
- `@modelcontextprotocol/server-google-maps` - Maps/directions
- `@modelcontextprotocol/server-puppeteer` - Browser automation
- See: https://github.com/modelcontextprotocol/servers

**Pros:** Pre-built, tested, community support
**Cons:** Docker/npx overhead, external dependency

#### Option 3: n8n Workflow
Best for: Complex integrations, visual design, auth handling

```bash
# n8n exposes workflows as webhooks
# Create workflow in n8n UI, then call via send_webhook

# Example: Slack message via n8n
./orchestrator/orchestrator_v2.py cloud "Send a Slack message to #general: Hello team!"
# → Uses send_webhook to trigger n8n workflow
```

**n8n Advantages:**
- 400+ pre-built integrations (Slack, Google, Notion, etc.)
- OAuth handling built-in
- Visual workflow debugging
- Can combine multiple services in one call

**Recommended n8n Workflows:**
| Workflow | Triggers | Actions |
|----------|----------|---------|
| `slack-message` | Webhook | Slack: Post Message |
| `calendar-events` | Webhook | Google Calendar: Get Events |
| `spotify-control` | Webhook | Spotify: Play/Pause/Search |
| `todoist-tasks` | Webhook | Todoist: Create/List Tasks |
| `sms-alert` | Webhook | Twilio: Send SMS |

---

### Quick Win Tools (Easy to Add)

These remaining tools can be implemented in < 1 hour:

#### 1. File Search Tool
```python
# skills/file_search.py
import subprocess
result = subprocess.run(['find', path, '-name', pattern], capture_output=True)
# Or use ripgrep for content search:
result = subprocess.run(['rg', '-l', pattern, path], capture_output=True)
```

#### 2. Clipboard Tool
```python
# skills/clipboard.py
import pyperclip
content = pyperclip.paste()  # Read
pyperclip.copy(text)         # Write
```

#### 3. Translate Tool
```python
# skills/translate.py
from googletrans import Translator
translator = Translator()
result = translator.translate(text, dest=target_lang)
```

#### 4. RSS Feed Tool
```python
# skills/rss_feed.py
import feedparser
feed = feedparser.parse(url)
entries = [{'title': e.title, 'link': e.link} for e in feed.entries[:10]]
```

---

### Tool Categories - Current Status

| Category | Rating | Tools | Notes |
|----------|--------|-------|-------|
| **Memory & Context** | ⭐⭐⭐⭐⭐ | 7 tools + deep_memory_search | Excellent - FTS5, semantic, cross-source |
| **Development/Coding** | ⭐⭐⭐⭐⭐ | opencode, execute_bash, ssh_remote, docker_control | OpenCode is powerful, SSH for remote |
| **Web Search & Scraping** | ⭐⭐⭐⭐⭐ | brave_search, crawl_url, screenshot_url, fetch | Stealth scraping, vision analysis |
| **Communication** | ⭐⭐⭐⭐ | send_email, phone_call, send_webhook, samantha | Missing: Slack, Discord |
| **Productivity** | ⭐⭐⭐⭐ | calendar (n8n), reminders, alerts, canvas, stash | Missing: Todoist, Notion |
| **Media** | ⭐⭐⭐⭐⭐ | spotify, generate_music, youtube_transcript | Full Spotify control, AI music |
| **Finance** | ⭐⭐⭐⭐⭐ | crypto_price, stock_price, price_alert | Crypto, stocks, futures, forex, alerts |
| **Image & Vision** | ⭐⭐⭐⭐⭐ | generate_image, analyze_image, upload_cloudflare | AI gen, vision, CDN upload |
| **Documents** | ⭐⭐⭐⭐ | pdf_create, pdf_read, printer | Create, read, merge, split, print |
| **System/Local** | ⭐⭐⭐ | speaker_volume, system_monitor, network_tools | Missing: clipboard |
| **Smart Home** | ⭐ | (none) | Future: Home Assistant, MQTT |

---

### Recommended Next Steps

1. ✅ ~~**Add Weather**~~ - Done 11-29-2025
2. ✅ ~~**Add Calendar Integration**~~ - Done 11-26-2025
3. ✅ ~~**Add Spotify**~~ - Done
4. ✅ ~~**Add Stock Prices**~~ - Done
5. **Add Slack Integration** - n8n workflow for team comms
6. **Add File Search** - Local tool for workspace search
7. **Add Clipboard** - Quick data transfer

### MCP Servers to Consider

```bash
# GitHub (issues, PRs, repos)
npx -y @modelcontextprotocol/server-github

# Slack (messages, channels)
npx -y @modelcontextprotocol/server-slack

# Google Maps (directions, places)
npx -y @modelcontextprotocol/server-google-maps

```

---

## Playwright MCP Server (Browser Automation)

[Playwright MCP Server](https://github.com/microsoft/playwright-mcp)

### Why Playwright?

| Scenario | `fetch` MCP | `playwright` MCP |
|----------|-------------|------------------|
| Static HTML pages | ✅ Fast, lightweight | ⚠️ Overkill |
| JavaScript SPAs (React, Vue) | ❌ Returns empty HTML | ✅ Renders JS first |
| Login/authentication flows | ❌ No session handling | ✅ Full browser state |
| Form filling & submission | ❌ No interaction | ✅ Click, type, submit |
| Screenshots & PDFs | ❌ Not supported | ✅ Built-in |
| CAPTCHA handling | ❌ No | ⚠️ Basic (vision mode) |

**Rule of thumb:** Try `fetch` first. If page is blank/broken, switch to `playwright`.

### Configuration (Headless Ubuntu)

```json
"playwright": {
  "command": "docker",
  "args": [
    "run", "-i", "--rm", "--init",
    "--network", "host",
    "-v", "/tmp/playwright-output:/output",
    "mcr.microsoft.com/playwright/mcp",
    "--headless",
    "--no-sandbox",
    "--browser", "chromium",
    "--caps", "pdf",
    "--timeout-action", "30000",
    "--timeout-navigation", "60000",
    "--viewport-size", "1920x1080"
  ],
  "description": "Browser automation for JS-heavy sites",
  "enabled": true
}
```

### Key Options Explained

| Flag | Purpose | Home Lab Recommendation |
|------|---------|------------------------|
| `--headless` | No display required | ✅ Required for Ubuntu server |
| `--no-sandbox` | Docker compatibility | ✅ Required in containers |
| `--browser chromium` | Browser engine | Chromium (default, fastest) |
| `--caps pdf` | Enable PDF generation | Optional, adds `browser_pdf_save` |
| `--caps vision` | Coordinate-based clicks | For complex UI automation |
| `--timeout-action 30000` | 30s per action (click, type) | Increase for slow sites |
| `--timeout-navigation 60000` | 60s for page loads | Increase for heavy pages |
| `--viewport-size 1920x1080` | Screen size | Standard desktop |
| `--isolated` | Memory-only, no disk | Security for untrusted sites |

### Advanced Options

```json
// Add to args array as needed:
"--allowed-origins", "https://trusted.com",     // Restrict navigation
"--blocked-origins", "https://ads.com",         // Block domains
"--proxy-server", "http://yourproxy:3128",      // Route through proxy currently does not support http://user:pass@host:port
"--user-agent", "Mozilla/5.0...",               // Custom UA
"--storage-state", "/state/state.json",         // Persist cookies/auth
"--save-trace"                                   // Debug traces to /output
```

### Playwright Tools Available

| Tool | Description | Example Use |
|------|-------------|-------------|
| `browser_navigate` | Go to URL | Navigate to login page |
| `browser_click` | Click element | Click "Submit" button |
| `browser_type` | Type into field | Fill username/password |
| `browser_snapshot` | Get page accessibility tree | Better than screenshot for LLM |
| `browser_take_screenshot` | Capture image | Visual verification |
| `browser_pdf_save` | Save page as PDF | Generate reports |
| `browser_evaluate` | Run JavaScript | Extract dynamic data |
| `browser_select_option` | Dropdown selection | Choose from menus |
| `browser_wait_for` | Wait for element/text | Handle loading states |
| `browser_tabs` | Manage tabs | Multi-tab workflows |

### Example Workflows

**1. Scrape JS-heavy dashboard:**
```
User: "Get my server stats from the Proxmox dashboard"
→ browser_navigate(url="https://proxmox:8006")
→ browser_type(ref="#username", text="root")
→ browser_type(ref="#password", text="***")
→ browser_click(ref="#login-btn")
→ browser_snapshot() → Extract stats from accessibility tree
```

**2. Generate PDF report:**
```
User: "Save this webpage as PDF"
→ browser_navigate(url="https://example.com/report")
→ browser_pdf_save(filename="report.pdf")
```

**3. Fill web form:**
```
User: "Submit a support ticket on the portal"
→ browser_navigate(url="https://support.example.com")
→ browser_type(ref="#subject", text="Server issue")
→ browser_type(ref="#description", text="...")
→ browser_click(ref="#submit")
```

### When NOT to Use Playwright

- Simple API calls → Use `api_call` tool
- Static HTML pages → Use `fetch` MCP (10x faster)
- File downloads → Use `fetch` or `api_call`
- Frequent polling → Too slow, use dedicated monitoring

### Troubleshooting

```bash
# Test Playwright MCP manually
docker run -it --rm mcr.microsoft.com/playwright/mcp --help

# Check if running
docker ps | grep playwright

# View screenshots/PDFs
ls -la /tmp/playwright-output/

# Increase timeout for slow sites
# Add: "--timeout", "120000" (2 minutes)
```

### Security Notes

- **Headless Ubuntu:** `--no-sandbox` is safe inside Docker
- **Allowed origins:** Restrict to trusted domains in production
- **Storage state:** Mount read-only (`/host/state:/state:ro`)
- **Isolated mode:** Use `--isolated` for untrusted URLs
