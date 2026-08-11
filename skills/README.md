# Skills / Tools

This directory contains 80+ built-in executable tools, plus Tool Builder output
under `auto-tools/`. Each tool is a Python script paired with a JSON definition
file.

---

## Directory Structure

```
skills/
├── *.py              # Tool scripts (executable)
├── *.tool.json       # Tool definitions (schema, permissions)
├── auto-tools/       # Tools created by Tool Builder
│   ├── *.py
│   ├── *.tool.json
│   └── *.report.json # Build audit reports
└── profiles/         # Tool profile overlays (tracked baselines + examples/)
```

### Tool profiles (optional)

Each profile is `skills/profiles/<name>.json` with `{"description": "...", "overrides": {"tool_name": false}}`. Keys in `overrides` win over the `enabled` flag in `*.tool.json`. Omit a tool to leave the file’s setting unchanged.

Set **`JARVIS_TOOL_PROFILE`** in `config/local.env` or `config/cloud.env` to the
profile **name** (stem of the file under `skills/profiles/`, default: `default`).
Tracked ready-to-use baselines include **`default.json`**, **`openai_only.json`**,
**`docker.json`**, and **`docker-mcp.json`**. Other custom profile JSON files in
`skills/profiles/` are gitignored. **Copy-paste templates** live in
**`skills/profiles/examples/`** (tracked); copy one to
`skills/profiles/<name>.json` and set `JARVIS_TOOL_PROFILE=<name>`. For Docker,
see the tracked **`docker.json`** profile and
[docs/docker/README.md](../docs/docker/README.md).

After changing profile: restart Jarvis services, then run `./bin/sync-tools.py local` or `./bin/sync-tools.py cloud`. Inspect: `./bin/manage-tools.py profile show`.

For a new OpenAI cloud install with only `OPENAI_API_KEY`, select
`JARVIS_TOOL_PROFILE=openai_only`. It keeps OpenAI-backed tools and useful
credential-free tools, while disabling integrations that need another
credential, personal configuration, or external service. The profile does not
select the LLM provider; keep `LLM_PROVIDER=openai` in `config/cloud.env`.

Example custom profile you can copy to `skills/profiles/<your_name>.json` and
edit (custom names are gitignored; the ready-to-use baselines are listed above):

```json
{
  "description": "Short note for yourself (optional).",
  "overrides": {
    "workflow": false,
    "weather": false,
    "serpapi_amazon_search": false,
    "mcp_fetch_fetch": false,
    "mcp_brave_search_brave_web_search": false
  }
}
```

- Only tools listed under `overrides` are changed; every other tool still follows its `*.tool.json` `enabled` flag.
- If a tool is already **`"enabled": false`** in its `*.tool.json`, you do not need to repeat **`"tool_name": false`** in a profile for the same effect (unless you like documenting intent).
- Overrides may include **names that are not registered** (missing MCP server, typo, removed skill); they are **harmless** and do not raise—only registered tools read those entries.
- Use `true` to force-enable a tool that is disabled in the tool file (uncommon).
- Discover exact tool names (including `mcp_*`): `./bin/manage-tools.py list` or `./bin/manage-tools.py profile export` while the tools you care about are registered.

`tool_search` and `workflow` follow the same profile rules as every other tool. They are mandatory **discovery candidates only when they remain in the effective registry**; neither is force-enabled. Setting either name to `false` removes it from normal Tool RAG routing after services restart.

Disabling `workflow` here disables the autonomous `workflow(search|describe|run)` meta-tool. It does not disable the independent explicit slash-command or scheduled-workflow entry points. Those continue to validate every component tool against the active registry/profile before execution.

**Known gap:** profiles control which tools the router can *call*, and
tool-specific Intelligence insights are filtered against the effective live
registry. Meta Q&A (“what can you do?”) may still overstate disabled
capabilities from broad static prompt prose that is not generated from the
effective tool set. See [Runtime-Aware Capability Narration (Q&A)](../docs/ADVANCED_AI_TECHNIQUES.md#design-note-runtime-aware-capability-narration-qa).

CLI reference: `./bin/manage-tools.py -h` and the usage block at the top of `bin/manage-tools.py`.

---

## Tool Discovery

Tools are automatically discovered when they have:
1. A Python script: `toolname.py`
2. A JSON definition: `toolname.tool.json`
3. Executable permission: `chmod +x toolname.py`

The orchestrator loads tools from both `skills/` and `skills/auto-tools/`.

`ToolRegistry.list_tools()` returns the names that survived manifest enablement,
the active profile, mode-specific availability, and credential/config checks.
It is not a raw list of every `*.tool.json`. Web/request blocks are applied
after registry construction for that surface.

---

## Tool Definition Format

Every tool needs a `.tool.json` file:

```json
{
  "enabled": true,
  "name": "weather",
  "description": "Get current weather and forecast for a location",
  "script": "weather.py",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": "City name or location"
      }
    },
    "required": ["location"]
  },
  "permissions": {
    "dangerous": false,
    "network": true,
    "filesystem": false,
    "bash": false,
    "auto_approve": true
  }
}
```

### Availability (credential requirements)

Tools with hard configuration requirements declare them in an optional
`availability` block. The tool stays `"enabled": true` in git; at runtime
`lib/tool_availability.py` checks env keys, config files, and webhook registry
entries against the active mode. Tools with unmet requirements are excluded
from the registry and Tool RAG (shown as "needs config" in the Web UI) and
come back automatically after configuration is added and services restart or
`./bin/sync-tools.py <mode>` runs.

```json
{
  "availability": {
    "all_of_env": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
    "any_of_env": ["BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"],
    "config_files": ["data/.spotify_cache"],
    "webhook_registry": ["send_email"],
    "provider_setting": "IMAGE_TOOL_PROVIDER",
    "provider_default": "gemini",
    "provider_requirements": {
      "gemini": {"all_of_env": ["GEMINI_API_KEY"]},
      "openai": {"all_of_env": ["OPENAI_API_KEY"]}
    },
    "setup_hint": "Set the key in the active mode env file."
  }
}
```

Rules:
- All keys are optional; omit the block entirely for tools with no requirements.
- `all_of_env`: every key must be set. `any_of_env`: at least one key must be set.
- `config_files`: every listed path must be a non-empty regular file. Relative
  paths resolve from the project root; `~` and absolute paths are supported.
  File contents are never read or returned by the evaluator.
- `webhook_registry`: each named entry in `config/webhook_registry.json` must
  exist, not be explicitly disabled (`enabled: false`), and have a non-blank
  URL after `${ENV_VAR}` substitution. URL values are never logged.
- `provider_requirements`: the tool is available when at least ONE provider's
  keys are configured (used by multi-provider tools like `generate_image`).
- Only presence is checked — secret values and file contents are never read into
  logs or the UI.
- A malformed block fails closed (that tool is treated as unavailable) and is
  reported by `./bin/manage-tools.py --mode <mode> list` and sync-tools output.
- Availability runs AFTER profile resolution: a profile cannot force-enable a
  tool whose hard requirement is missing.

### Schema Rules For Reliable Tool Calling

For best cross-provider compatibility, keep the top-level `parameters` schema simple:
- `"type": "object"`
- `"properties": { ... }`
- optional `"required": [...]`
- optional `"additionalProperties": false`

Do **not** rely on these at the top level of `parameters`:
- `allOf`
- `anyOf`
- `oneOf`
- `not`
- `if` / `then` / `else`
- `dependentSchemas`
- top-level `enum`

Why:
- OpenAI tool calling is stricter than full JSON Schema and can reject the entire request if one tool has unsupported top-level schema constructs.
- Anthropic may accept more, but the safest shared subset is still plain object + properties.
- Jarvis now sanitizes some unsupported OpenAI schema keywords before sending tools, but new tools should still be authored in the strict subset first.

If you need conditional validation, do it in the tool script itself:
- accept the input schema at the tool-calling layer
- validate combinations like “`group_ids` required when `action=apply`” inside Python
- return a structured error message if inputs are invalid

---

## Tool Contract

### Input
JSON object passed as command line argument:
```bash
./weather.py '{"location": "Portland, OR"}'
```

### Output
JSON object printed to stdout:
```json
{
  "ok": true,
  "speech": "It's 72 degrees and sunny in Portland",
  "data": {
    "temp": 72,
    "condition": "sunny",
    "location": "Portland, OR"
  }
}
```

### Exit Code
- `0`: Success
- Non-zero: Error (with error message in output)

---

## Available Tools (80+)

### Memory
| Tool | Description |
|------|-------------|
| `remember` | Store facts, preferences, technical info |
| `recall` | Retrieve specific memories by category/key |
| `search_memory` | FTS5 full-text keyword search |
| `semantic_recall` | AI-powered conceptual search |
| `update_memory` | Modify existing memories |
| `forget` | Delete memories |
| `deep_memory_search` | Multi-source search (memory, canvas, stash, intel) |

### Conversations
| Tool | Description |
|------|-------------|
| `get_recent_conversations` | Access conversation history |
| `search_conversations` | Search past interactions |

### Media & Content
| Tool | Description |
|------|-------------|
| `generate_image` | AI image generation and editing with Gemini, OpenAI, or xAI |
| `analyze_image` | Vision analysis (Grok/Claude/GPT-4o) |
| [`document_ocr`](../docs/tools/document-ocr-tool/README.md) | Optional OVIS OCR and structured extraction for scanned PDFs/images |
| [`generate_music`](../docs/tools/generate-music-tool/README.md) | Catalog-backed AI music creation with ElevenLabs or Gemini Lyria |
| `pdf_create` | Generate PDFs from content |
| `pdf_read` | Extract text/images from PDFs |
| `screenshot_url` | Full-page screenshots with AI analysis |
| `crawl_url` | Web scraping with Crawl4AI |

### Storage & Output
| Tool | Description |
|------|-------------|
| `stash` | Artifact storage, including strict `image_url` ingestion for untrusted public raster images |
| `canvas` | Visual knowledge pages |
| `printer` | Print from stash/files (CUPS) |

### Communication
| Tool | Description |
|------|-------------|
| `send_email` | Email with HTML templates |
| `send_webhook` | Trigger webhooks (Slack, Discord, APIs) |
| `phone_call` | AI phone calls (Vapi.ai) |

### System & Network
| Tool | Description |
|------|-------------|
| `execute_bash` | Run shell commands |
| `ssh_remote` | SSH into remote hosts |
| `docker_control` | Docker/compose management |
| `network_tools` | Ping, DNS, port checks, traceroute |
| `system_monitor` | CPU, RAM, disk, processes |
| `speaker_volume` | Audio volume control |

### Integrations
| Tool | Description |
|------|-------------|
| `weather` | Weather forecasts (OpenWeatherMap) |
| `crypto_price` | Cryptocurrency prices |
| `stock_price` | Stock/futures/forex prices |
| `serpapi_amazon_search` | Amazon listing discovery and focused ASIN/product details through SerpApi |
| `serpapi_search_index` | Structured indexed-web source discovery with standard/deep recall, snippets, exact URLs, and workflow-ready pagination |
| `serpapi_google_images_light` | Existing web-image discovery with full-size URLs, thumbnails, source pages, dimensions, filters, follow-up references, and optional strict top-result Stash download |
| `serpapi_google_news_light` | Fast topic-specific Google News discovery with headlines, sources, snippets, grouped Top Stories, and exact article URLs |
| `serpapi_google_trends` | Query-driven Google Trends time series, regional comparisons, and rising/top related queries or topics |
| `serpapi_google_trending_now` | Seedless current-trend discovery with volume/growth signals and explicit selected-trend news drill-down |
| `serpapi_google_sports` | Google Sports schedules, scores, direct-game line or period scores, box scores, viewing options, recap links, standings, players, brackets, league stats, and rankings with optional query-to-KGMID resolution |
| `serpapi_ebay_search` | eBay listing discovery with prices, condition, shipping, images, and product IDs |
| `serpapi_ebay_product` | Focused eBay listing details by numeric product ID |
| `serpapi_home_depot` | SerpApi Home Depot product search with store/ZIP filters |
| `serpapi_google_local` | Google Local business discovery using explicit or mode-default location, with ratings, hours, service options, sponsored listings, related searches, and pagination |
| `serpapi_google_local_services` | Screened US professional-service providers from Google Local Services, with Google badges, contact/availability data, provider detail drill-down, and visible one- or two-search CID resolution |
| `serpapi_maps_search` | SerpApi Google Maps place and local business search |
| `serpapi_hotel_search` | Future Google Hotels options, cheapest-first stay pricing, and filters |
| `serpapi_travel_explore` | Flexible destination discovery with suggested dates, headline flight/hotel planning prices, and airport handoffs |
| `flight_search` | Future flight options and prices via SerpApi Google Flights or a keyless fallback |
| `serpapi_youtube` | SerpApi YouTube video details and transcript fallback |
| `serpapi_youtube_search` | SerpApi YouTube video search by keywords |
| `serpapi_yelp_search` | Yelp place discovery with local rating/review sorting, attrs, links, and optional review excerpts |
| `serpapi_tripadvisor` | Tripadvisor discovery plus place details, nearby suggestions, and filtered review drill-down by place ID |
| `trakt_movies` | Public Trakt movie discovery, related-title recommendations, current lists, metadata, and trailer/video links; requires a Trakt application Client ID |
| `trakt_account` | Optional read-only Trakt OAuth context: personalized recommendations, deterministic night-workflow watched filtering, watchlist, history, ratings, favorites, personal/smart lists, and up-next; requires Client Secret plus `./bin/trakt-auth` |
| `tmdb_movies` | Standalone TMDB movie search/discovery, rich details, posters/backdrops/logos, credits, videos, and recommendations; requires a TMDB API Read Access Token or v3 API key |
| `trakt_tv_shows` | Public Trakt TV-show discovery, related-series recommendations, current lists, typical episode runtime, metadata, and trailer/video links; requires a Trakt application Client ID |
| `tmdb_tv_shows` | Standalone TMDB TV search/discovery, rich series details, posters/backdrops/logos, aggregate credits, seasons, and recommendations; requires a TMDB API Read Access Token or v3 API key |
| `spotify` | Music playback control |
| `opencode` | Autonomous coding agent |
| `calculator` | Math, stats, unit conversions |

All 20 `serpapi_*` tools require `SERP_API_KEY` in the active mode env and are
excluded from that mode's callable registry and Tool RAG sync when it is absent.
`flight_search` can instead use its keyless fallback. See the full
[SerpApi tools guide](../docs/tools/serp-api-tool/README.md).

### Proactive System
| Tool | Description |
|------|-------------|
| `create_reminder` | Time-based reminders |
| `list_reminders` | View scheduled reminders |
| `acknowledge_reminders` | Clear reminders |
| `list_alerts` | View active alerts |
| `acknowledge_alerts` | Dismiss alerts |

### Development
| Tool | Description |
|------|-------------|
| `tool_search` | Discover enabled tools by summary first, then follow exact tool names |
| `workflow` | Discover, describe, and synchronously run an eligible deterministic workflow |
| `check_tool_logs` | View tool/workflow execution logs |
| `check_opencode_sessions` | Monitor OpenCode progress |
| `query_service_logs` | Check background service status |
| `ingest_intel` | Bulk import knowledge files |
| `manage_intel` | Create/manage intel files |

---

## Auto-Tools (Tool Builder)

The `auto-tools/` directory contains tools created by the Dynamic Tool Builder:

| Tool | Description |
|------|-------------|
| `docker_control` | Docker container and compose management |
| `network_tools` | Network diagnostics suite |
| `system_monitor` | System resource monitoring |
| `text_summarizer` | Text processing and analysis |
| `youtube_transcript` | Download YouTube transcripts |
| `status_recap` | Daily status aggregator |
| `generate_password` | Secure password generation |

Each auto-tool includes a `.report.json` with build audit information.

---

## Managing Tools

### Enable/Disable Tools
```bash
# List all tools
./bin/manage-tools.py list

# Disable a tool
./bin/manage-tools.py disable crypto_price

# Enable a tool
./bin/manage-tools.py enable crypto_price
```

### Sync Tools to LLM Context
```bash
# Sync for cloud mode
./bin/sync-tools.py cloud

# Sync for local mode
./bin/sync-tools.py local
```

---

## Creating New Tools

### 1. Use Tool Builder (Recommended)
```bash
./bin/build-tool --mode cloud build "Check if a URL is accessible"
```

### 2. Manual Creation

**Create the script (`skills/mytool.py`):**
```python
#!/usr/bin/env python3
import sys
import json

def main():
    # Parse input from command line
    input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    param = input_data.get("param", "default")
    
    # Do work...
    result = f"Processed: {param}"
    
    # Return JSON
    print(json.dumps({
        "ok": True,
        "speech": result,
        "data": {"param": param}
    }))

if __name__ == "__main__":
    main()
```

**Create the definition (`skills/mytool.tool.json`):**
```json
{
  "enabled": true,
  "name": "mytool",
  "description": "What the tool does - be specific for Tool RAG",
  "script": "mytool.py",
  "parameters": {
    "type": "object",
    "properties": {
      "param": {
        "type": "string",
        "description": "Parameter description"
      }
    },
    "required": ["param"]
  },
  "permissions": {
    "dangerous": false,
    "network": false,
    "filesystem": false,
    "bash": false,
    "auto_approve": true
  }
}
```

**Make executable and sync:**
```bash
chmod +x skills/mytool.py
./bin/sync-tools.py cloud
```

## Note

Every enabled local tool and every currently discovered MCP tool must have a
representative result payload in `tests/test_followup_tool_coverage.py`. The
bounded default extractor handles safe scalar handles and compact result lists.
Add a dedicated adapter or `FOLLOWUP_FIELDS` entry in
`jarvis-web/server/services/followup_extractor.py` when a tool returns nested
artifacts, content bodies, or another shape that needs special compaction.
Follow-up payloads must round-trip as strict JSON. Shortened text needs an
explicit `truncated for follow-up context` marker; shortened dictionaries and
lists need `_followup_truncated` metadata rather than sliced serialized JSON.

Print statements must have in tool *.py files file=sys.stderr so they are not printed to the console.

---

## Testing Tools

```bash
# Direct execution
./skills/weather.py '{"location": "Seattle"}'

# Via orchestrator
./orchestrator/orchestrator_v2.py cloud "What's the weather in Seattle?"

# Check tool logs
./orchestrator/orchestrator_v2.py cloud "show recent tool logs"
```

---

## Tool RAG Integration

Tools are discovered dynamically using semantic search:
- Only relevant tools are loaded per query (reduces context)
- Tool descriptions are embedded for similarity matching
- Configured ghost tools are prioritized inside the final schema cap
- `tool_search` and `workflow` are mandatory discovery candidates when enabled
- Profile-disabled, manifest-disabled, unavailable, and request-blocked tools are never resurrected by the Tool RAG database

---

## Related Documentation

- **[TOOL_CALLING_SYSTEM.md](../docs/TOOL_CALLING_SYSTEM.md)** - How tool routing works
- **[TOOL_MANAGEMENT.md](../docs/TOOL_MANAGEMENT.md)** - Enable/disable tools
- **[TOOL_RAG_STRATEGY.md](../docs/TOOL_RAG_STRATEGY.md)** - Dynamic tool discovery
- **[TOOL_BUILDER.md](../docs/TOOL_BUILDER.md)** - Automatic tool creation
- **[STASH_SYSTEM.md](../docs/STASH_SYSTEM.md)** - Artifact storage for tools
