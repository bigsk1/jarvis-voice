# Jarvis Tools & MCP Servers Inventory

> Last updated: January 26, 2026

---

## 📦 Native Tools (skills/)


| Tool | Description |
|------|-------------|
| `acknowledge_alerts` | Acknowledge/dismiss alerts |
| `acknowledge_reminders` | Acknowledge reminders |
| `analyze_image` | Analyze images with vision models |
| `api_call` | Make HTTP API requests |
| `calculator` | Math calculations |
| `canvas` | Visual knowledge pages (create, list, read) |
| `check_opencode_sessions` | Check OpenCode tmux sessions |
| `check_tool_logs` | View tool execution logs |
| `crawl_url` | Crawl/scrape web pages |
| `create_reminder` | Create time-based reminders (supports multi-day patterns) |
| `crypto_price` | Get cryptocurrency prices |
| `deep_memory_search` | Comprehensive search across all data sources |
| `evolution_test` | Test tool for prompt evolution |
| `execute_bash` | Execute bash commands |
| `forget` | Remove memories |
| `generate_image` | AI image generation (Google Imagen) |
| `generate_music` | ElevenLabs music generation |
| `get_recent_conversations` | Get recent terminal conversations |
| `get_time` | Get current time/date |
| `ingest_intel` | Ingest intel documents |
| `list_alerts` | List active alerts |
| `list_reminders` | List pending reminders |
| `manage_intel` | Manage intel folder |
| `opencode` | AI coding assistant (isolated workspace) |
| `pdf_create` | Create PDF documents |
| `pdf_read` | Read/extract text from PDFs, merge, split, search |
| `phone_call` | Make phone calls |
| `price_alert` | Manage price alerts for crypto/stocks/futures (n8n monitored) |
| `printer` | Print documents |
| `query_service_logs` | Query systemd service logs |
| `recall` | Recall specific memory by key |
| `remember` | Store new memories |
| `samantha` | Contact Samantha AI assistant on VPS2 (multi-agent) |
| `screenshot_url` | Screenshot web pages |
| `search_conversations` | Search conversation history |
| `search_memory` | FTS5 keyword search in memories |
| `semantic_recall` | AI semantic search in memories |
| `send_email` | Send emails via n8n |
| `send_webhook` | Send webhooks |
| `speaker_volume` | Control speaker volume |
| `spotify` | Spotify playback control |
| `ssh_remote` | Execute commands on remote hosts via SSH |
| `stash` | Temporary artifact storage |
| `stock_price` | Get stock/futures/commodity/forex prices (yfinance) |
| `update_memory` | Update existing memories |
| `weather` | Get weather information |

### 🤖 Auto-Tools (skills/auto-tools/)

*Tools created by Tool Builder or for specialized operations*

| Tool | Description |
|------|-------------|
| `docker_control` | Docker containers, compose, images, networks, exec, prune |
| `generate_password` | Generate secure passwords with various options |
| `network_tools` | Ping, DNS lookup, port scanning, HTTP/HTTPS checks, traceroute |
| `status_recap` | Daily status briefing (weather, crypto, stocks, alerts, system, canvas) |
| `system_monitor` | CPU, memory, disk, processes, network stats |
| `text_summarizer` | Text summarization, keyword extraction, word/char counts |
| `youtube_transcript` | Download YouTube transcripts as .srt/.md files |

---

## 🔌 MCP Servers (Jarvis)

> Config: `config/mcp-servers.json`

### ✅ Enabled (2)

| Server | Container | Description |
|--------|-----------|-------------|
| `fetch` | `mcp/fetch` | Fetch URLs as markdown (ignores robots.txt) |
| `brave_search` | `mcp/brave-search` | Web search via Brave API (Pro AI key) |

### ❌ Disabled (2)

| Server | Container | Description | Reason |
|--------|-----------|-------------|--------|
| `sequentialthinking` | `mcp/sequentialthinking` | Step-by-step reasoning | Not needed currently |
| `playwright` | `mcr.microsoft.com/playwright/mcp` | Browser automation | Heavy, use crawl_url instead |


---

## 🚫 Blocked Tools

> Config: `BLOCKED_TOOLS` in `config/cloud.env`

| Tool | Reason |
|------|--------|
| `mcp_blinko_webSearch` | Redundant with brave_search |
| `mcp_blinko_webExtra` | Redundant |

---

## 📝 Future Tools Ideas

*Add ideas for new tools here:*

| Idea | Priority | Notes |
|------|----------|-------|
| | | |
| | | |
| | | |

---

## 📊 Stats

- **Total Native Tools**: 53
  - Core Skills (skills/): 46 enabled
  - Auto-Tools (skills/auto-tools/): 7 enabled
- **Total MCP Servers (Jarvis)**: 4
  - Enabled: 2
  - Disabled: 2
- **Cursor MCP Servers**: 2
