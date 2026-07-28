# Workflow Building Guide for AI Agents

> **Purpose**: Reference for building workflows correctly the first time
> **Critical**: Always verify tool return structures before writing extract rules

---

## Step 1: Understand the Tool BEFORE Writing the Workflow

**Never assume tool return fields. Always test first.**

```bash
# Test any tool to see its actual return structure:
cd ~/jarvis-voice
.venv/bin/python << 'PYEOF'
import sys, json
sys.path.insert(0, 'orchestrator')
sys.path.insert(0, 'lib')
from config_loader import load_config
from executor import ToolExecutor

load_config('cloud')
exec = ToolExecutor('cloud')

# Replace with tool and params you need
result = exec.execute('TOOL_NAME', {'param': 'value'})
print(json.dumps(result, indent=2, default=str))
PYEOF
```

---

## Step 2: Tool Return Structures (Verified)

### ssh_remote
```python
# Params: action="run", host="vps2", command="uptime"
{
  "ok": true,
  "data": {
    "host": "vps2",
    "command": "uptime",
    "exit_code": 0,
    "stdout": "output here",    # <- Use this, NOT "output"
    "stderr": null,
    "truncated": false
  }
}
```
**Extract rules:**
```json
"extract": {"ssh_output": "stdout", "exit_code": "exit_code"}
```

### stash (save action)
```python
# Params: action="save", kind="text", text="content", name="file.txt"
# Also supports: kind="json" (json={}), kind="base64" (data="..."), 
#               kind="url" (url="https://..."), kind="file" (file_path="/tmp/...")
{
  "ok": true,
  "data": {
    "space_id": "space_20260122_...",
    "file_id": "f_abc123",
    "ref": "stash://space_.../f_abc123",  # <- Use "ref", NOT "file_ref"
    "name": "file.txt",
    "path": "/full/path/to/file.txt",
    "mime_type": "text/plain",
    "size_bytes": 123
  }
}
```
**Extract rules:**
```json
"extract": {"stash_ref": "ref", "space_id": "space_id"}
```

**File kind** (for local files like screenshots):
```json
"params": {
  "action": "save",
  "kind": "file",
  "file_path": "${screenshot_path}",
  "name": "screenshot.jpg"
}
```
**Security**: Only `/tmp` and project directories allowed for `file_path`.

### stash (open_space action)
```python
# Params: action="open_space", labels=["research"]
{
  "ok": true,
  "data": {
    "space_id": "space_20260122_...",
    "path": "/full/path/to/space"
  }
}
```
**Extract rules:**
```json
"extract": {"space_id": "space_id"}
```

### screenshot_url
```python
# Params: url="https://example.com", wait=3, analyze=true, question="Describe this page"
{
  "ok": true,
  "data": {
    "url": "https://example.com",
    "screenshot_path": "/tmp/screenshot_20260125_123456.jpg",  # <- Local file path
    "size_bytes": 125998,
    "wait_seconds": 3,
    "analysis": "This page shows..."  # <- Vision AI analysis (if analyze=true)
  }
}
```
**Extract rules:**
```json
"extract": {"screenshot_path": "screenshot_path", "vision_analysis": "analysis"}
```
**Pattern**: Use with stash `file` kind to save screenshot:
```json
{
  "step": 2,
  "tool": "screenshot_url",
  "params": {"url": "${url}", "analyze": true, "wait": 3},
  "extract": {"screenshot_path": "screenshot_path", "vision_analysis": "analysis"}
},
{
  "step": 3,
  "tool": "stash",
  "action": "save",
  "params": {"kind": "file", "file_path": "${screenshot_path}", "name": "screenshot.jpg"},
  "extract": {"screenshot_ref": "ref"}
}
```
**Note**: Vision analysis is often more reliable than crawling for sites with bot protection.

### get_time
```python
# Params: {} (no params needed)
{
  "ok": true,
  "data": {
    "time": "09:07",
    "time_12h": "09:07 AM",
    "date": "2026-01-22",
    "date_formatted": "Thursday, January 22, 2026",
    "day_of_week": "Thursday",
    "timezone": "local"
  }
}
```
**Extract rules:**
```json
"extract": {"check_date": "date_formatted", "check_time": "time_12h"}
```

### crawl_url
```python
# Params: url="https://example.com"
{
  "ok": true,
  "data": {
    "results": [
      {
        "url": "https://example.com",
        "title": "Page Title",
        "markdown": "# Full page content..."
      }
    ]
  }
}
```
**Built-in transform**: Pipeline executor automatically creates `${article.url}`, `${article.title}`, `${article.content}` from crawl_url results. No extract needed.

### canvas (create action)
```python
# Params: action="create", title="My Page", content="...", tags=["tag1"]
{
  "ok": true,
  "data": {
    "page_id": "page_20260122_...",
    "title": "My Page",
    "url": "http://localhost:5123/canvas/page_..."
  }
}
```
**Extract rules:**
```json
"extract": {"canvas_id": "page_id"}
```

### crypto_price
```python
# Params: coin="bitcoin" or coin="solana"
{
  "ok": true,
  "data": {
    "coin": "Bitcoin",           # Display name
    "coin_id": "bitcoin",        # CoinGecko ID
    "price_usd": 89436,          # <- Use this
    "change_24h_percent": 1.77,  # <- Use this
    "market_cap_usd": 1787245973310.0,
    "source": "CoinGecko"
  }
}
```
**Extract rules:**
```json
"extract": {"btc_price": "price_usd", "btc_change": "change_24h_percent"}
```

### send_email
```python
# Params: to="boss", subject="...", body="..."
{
  "ok": true,
  "data": {
    "to": "boss@example.com",
    "to_name": "Boss",
    "subject": "Email subject",
    "status": "sent"
  }
}
```
**Note**: `body` parameter is required. When using `llm_prompt`, the LLM-generated content is automatically mapped to `body`.

### remember
```python
# Params: key="Important fact", value="Details here", category="notes"
{
  "ok": true,
  "data": {
    "memory_id": 123,
    "key": "Important fact"
  }
}
```
**Extract rules:**
```json
"extract": {"memory_id": "memory_id"}
```

### brave_search
```python
# Params: query="search term"
{
  "ok": true,
  "data": {
    "query": "search term",
    "results": [
      {"title": "...", "url": "https://...", "description": "..."},
      ...
    ]
  }
}
```
**Built-in transform**: Pipeline executor automatically creates `${search_results.urls}` array.

### weather
```python
# Params: location="${location}" — prefer workflow variable from JARVIS_DEFAULT_LOCATION (see README Variables)
{
  "ok": true,
  "data": {
    "location": "City, Region",
    "temperature": 36,
    "feels_like": 34,
    "humidity": 79,
    "condition": "overcast clouds",
    "wind_speed": 3,
    "wind_unit": "mph"
  }
}
```
**Extract rules:**
```json
"extract": {"temperature": "temperature", "humidity": "humidity", "condition": "condition"}
```

### stock_price
```python
# Params: symbol="TSLA" or symbol="GC=F" (gold futures)
{
  "ok": true,
  "data": {
    "symbol": "TSLA",
    "company": "Tesla, Inc.",
    "price_usd": 449.36,
    "change_today_percent": 3.26,
    "market_cap_usd": 1490000000000,
    "pe_ratio": 312.1,
    "sector": "Consumer Cyclical"
  }
}
```
**Extract rules:**
```json
"extract": {"tsla_price": "price_usd", "tsla_change": "change_today_percent"}
```

### system_monitor
```python
# Params: {} (no params needed)
{
  "ok": true,
  "data": {
    "cpu": {"total_percent": 0.3, "per_cpu": [...]},
    "memory": {"ram": {"percent_used": 15.4, "used_gb": 4.6, "total_gb": 30.1}},
    "uptime": {"uptime_string": "8d 20h 3m"},
    "disks": [{"mountpoint": "/", "percent_used": 5.3}]
  }
}
```
**Extract rules (nested paths):**
```json
"extract": {
  "cpu_percent": "cpu.total_percent",
  "memory_percent": "memory.ram.percent_used",
  "uptime": "uptime.uptime_string"
}
```

### list_alerts
```python
# Params: status="pending"
{
  "ok": true,
  "data": {
    "count": 3,
    "alerts": [
      {"id": 350, "message": "Gold moved...", "severity": "high", "status": "pending"}
    ]
  }
}
```
**Extract rules:**
```json
"extract": {"alert_count": "count", "alerts": "alerts"}
```

### list_reminders
```python
# Params: status="scheduled", limit=5
{
  "ok": true,
  "data": {
    "count": 2,
    "reminders": [
      {"id": 10, "title": "Call mom", "relative_time": "in 2 hours"}
    ]
  }
}
```
**Extract rules:**
```json
"extract": {"reminder_count": "count", "reminders": "reminders"}
```

### generate_image
```python
# Params: prompt="...", aspect_ratio="landscape" (optional)
{
  "ok": true,
  "data": {
    "prompt": "Original prompt",
    "revised_prompt": "Enhanced prompt",
    "saved": {
      "stash_ref": "stash://space_.../f_abc123",
      "memory_id": 456
    }
  }
}
```
**Extract rules:**
```json
"extract": {"image_ref": "saved.stash_ref"}
```
**LLM prompt example** (llm_prompt fills the `prompt` param):
```json
"llm_prompt": "Create a dashboard image showing: Weather ${temperature}°F, Bitcoin $${btc_price}. Style: dark theme, neon accents, futuristic HUD."
```
Note: The LLM will generate a text description for the image, NOT ASCII art.

### youtube_transcript
```python
# Params: url="https://youtube.com/watch?v=..."
{
  "ok": true,
  "data": {
    "video_title": "Video Title Here",
    "srt_filename": "Video_Title_Here_transcript.srt",
    "md_filename": "Video_Title_Here_transcript.md",
    "srt_saved": true,
    "md_saved": true,
    "srt_stash_ref": "stash://space_.../f_abc123",
    "md_stash_ref": "stash://space_.../f_def456",
    "space_id": "space_20260124_...",
    "transcript_length": 12345
  }
}
```
**Extract rules:**
```json
"extract": {
  "video_title": "video_title",
  "space_id": "space_id",
  "md_filename": "md_filename",
  "md_stash_ref": "md_stash_ref"
}
```
**Note**: Tool auto-saves to stash. Use `stash` action `read` with `space_id` and `file_id: md_filename` to get transcript content.

### text_summarizer
```python
# Params: text="...", operation="summarize", num_sentences=3
{
  "ok": true,
  "data": {
    "summary": "Extracted summary sentences..."
  }
}

# Params: text="...", operation="keywords", top_n=10
{
  "ok": true,
  "data": {
    "keywords": [
      {"keyword": "python", "frequency": 15},
      {"keyword": "machine", "frequency": 12}
    ]
  }
}

# Params: text="...", operation="count"
{
  "ok": true,
  "data": {
    "statistics": {
      "words": 500,
      "characters_with_spaces": 3000,
      "sentences": 25,
      "paragraphs": 5
    }
  }
}

# Params: text="...", operation="sentiment"
{
  "ok": true,
  "data": {
    "sentiment": {
      "sentiment": "positive",
      "confidence": 0.75,
      "positive_words": 10,
      "negative_words": 3
    }
  }
}
```
**Extract rules (for summarize):**
```json
"extract": {"summary": "summary"}
```
**Extract rules (for keywords):**
```json
"extract": {"keywords": "keywords"}
```

### manage_intel
```python
# Params: action="create", path="topic-name.md", content="...", auto_ingest=true
{
  "ok": true,
  "data": {
    "file": "topic-name.md",
    "size_bytes": 1234,
    "created": true,
    "ingest": {
      "ingested": true,
      "new_files": 1,
      "total_facts": 15
    }
  }
}

# Params: action="list"
{
  "ok": true,
  "data": {
    "files": [{"path": "file1.md", "size_bytes": 500}, ...],
    "count": 5
  }
}
```
**Extract rules:**
```json
"extract": {"intel_file": "file", "facts_added": "ingest.total_facts"}
```
**Note**: Use `auto_ingest: true` to automatically add facts to memory after creating/updating the intel file.

### search_memory
```python
# Params: query="collection xai", limit=5
{
  "ok": true,
  "data": {
    "query": "collection xai",
    "count": 3,
    "results": [
      {"id": 123, "key": "xAI Collections - file", "value": "A file is...", "category": "technical"},
      ...
    ]
  }
}
```
**Extract rules:**
```json
"extract": {"found_count": "count", "found_items": "results"}
```
**Note**: Useful as a final verification step to confirm ingestion worked.

---

## Step 3: Workflow JSON Structure

### Minimal Working Example
```json
{
  "id": "unique_id",
  "name": "Display Name",
  "description": "What it does",
  "enabled": true,
  "version": "1.0",
  
  "triggers": {
    "explicit": ["/command"]
  },
  
  "variables": {
    "topic": {"from": "query", "extract": "main_subject"}
  },
  
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "params": {"key": "${topic}"},
      "output_var": "result1",
      "extract": {"var_name": "field_path"},
      "required": true
    }
  ],
  
  "success_speech": "Done with ${topic}.",
  "abort_speech": "Failed."
}
```

### Variable Definitions

Implementation reference: `orchestrator/pipeline_executor.py` (`_extract_workflow_variables`). Authoring summary: [README.md](README.md).

Runtime always includes `query`, `topic`, `content` (alias of `topic`), `workflow_id`, and `timestamp`.

**Simple static values** (strings, numbers, booleans — copied as-is):
```json
"variables": {
  "timeout": 30,
  "dry_run": false,
  "label": "example-label"
}
```

**From environment** (reads `os.environ`; set values in `config/cloud.env` or `config/local.env`). Use this for **default geography** instead of hardcoding a city in JSON:
```json
"variables": {
  "location": {
    "from": "env",
    "key": "JARVIS_DEFAULT_LOCATION",
    "default": "City, Region"
  }
}
```

**From static object:**
```json
"variables": {
  "mode": { "from": "static", "value": "summarize" }
}
```

**Dynamic extraction from query:**
```json
"variables": {
  "url": { "from": "query", "extract": "url" },
  "topic": { "from": "query", "extract": "main_subject" },
  "host": { "from": "query", "extract": "main_subject", "default": "vps2" },
  "url_domain": { "from": "url", "transform": "domain", "default": "unknown" }
}
```

**`extract` values for `from`: `"query"`:** `main_subject`, `url`, `short_title`, `first_words` (optional `max_words`, default 4).

**Second-pass transforms** (`transform` + `from` naming another variable): `domain`, `lowercase`, `uppercase`, `strip`.

**Examples:**
- `/archive bigsk1.com` → `url="https://bigsk1.com"`, `topic="bigsk1.com"`
- `/health` → `host="vps2"` (default)
- `/health vps20` → `host="vps20"`
- `/dive https://cursor.com/pricing` → `url_domain="cursor.com"`

### Step Fields Reference

| Field | Required | Description |
|-------|----------|-------------|
| `step` | Yes | Step number (for ordering/logging) |
| `tool` | Yes | Tool name to execute |
| `action` | No | For tools with actions (stash, canvas) |
| `params` | No | Tool parameters, supports `${variables}` |
| `output_var` | No | Store full result in variable |
| `extract` | No | Extract specific fields: `{"var": "path"}` |
| `llm_prompt` | No | LLM generates `content` param from this |
| `required` | No | Default `true`. Abort workflow if fails |
| `on_fail` | No | `"continue"` to proceed despite failure |
| `description` | No | For logging |

### Variable Syntax

| Syntax | Example | Description |
|--------|---------|-------------|
| `${var}` | `${topic}` | Simple variable |
| `${obj.key}` | `${article.url}` | Nested path |
| `${arr[0]}` | `${urls[0]}` | Array index |
| `${arr[:N]}` | `${urls[:5]}` | First N items |

---

## Step 4: Common Mistakes

### Wrong Field Names
```json
// WRONG - ssh_remote returns "stdout", not "output"
"extract": {"ssh_output": "output"}

// CORRECT
"extract": {"ssh_output": "stdout"}
```

### Wrong Stash Params
```json
// WRONG - stash save expects "text", not "content"
"params": {"kind": "text", "content": "${data}"}

// CORRECT
"params": {"kind": "text", "text": "${data}"}
```

### Missing Action Parameter
```json
// WRONG - ssh_remote requires "action"
"params": {"host": "vps2", "command": "uptime"}

// CORRECT
"params": {"action": "run", "host": "vps2", "command": "uptime"}
```

### Extract Paths Include "data." Prefix
```json
// WRONG - extract paths are relative to result.data, don't include "data."
"extract": {"temperature": "data.temperature", "cpu": "data.cpu.total_percent"}

// CORRECT - paths start from inside data
"extract": {"temperature": "temperature", "cpu": "cpu.total_percent"}
```

### Assuming Built-in Transforms Exist
Only these tools have automatic transforms:
- `crawl_url` → creates `${article.title}`, `${article.content}`, `${article.url}`
- Search tools → creates `${search_results.urls}`

All other tools require explicit `extract` rules.

### LLM Prompt Echoes Variable Placeholders
```json
// WRONG - LLM will output "${crawled_url}" literally in canvas
"llm_prompt": "Create a summary. Include: Source URL: ${crawled_url}"

// CORRECT - Tell LLM to use actual values
"llm_prompt": "Create a summary.\n\nINPUT DATA:\n- URL: ${crawled_url}\n\nIMPORTANT: Use the actual values from the input data above - do not output placeholder syntax like ${var}.\n\n**References**\n- Source: [write the actual URL from the input data]"
```
The LLM receives resolved values but may echo the placeholder syntax if instructed to include `${var}` in output.

### Making All Steps Required
```json
// WRONG - crawl_url failures abort entire workflow
"required": true  // default

// CORRECT for optional steps - workflow continues if step fails
"required": false,
"on_fail": "continue"
```
Use `required: false` for steps that may fail (crawling protected sites, screenshots blocked by bot protection).

---

## Step 5: Testing Workflow

### Quick CLI Test
```bash
cd ~/jarvis-voice
.venv/bin/python ./orchestrator/orchestrator_v2.py cloud "/command args"
```

### Detailed Debug Test
```bash
cd ~/jarvis-voice
.venv/bin/python << 'PYEOF'
import sys, json
sys.path.insert(0, 'orchestrator')
sys.path.insert(0, 'lib')
from config_loader import load_config
from orchestrator_v2 import Orchestrator

load_config('cloud')
orch = Orchestrator(mode='cloud')
result = orch.process('/command args')

print(f"ok: {result.get('ok')}")
print(f"speech: {result.get('speech')}")
for r in result.get('data', {}).get('results', []):
    print(f"  Step {r.get('step')}: {r.get('tool')} - ok={r.get('ok')}")
    if not r.get('ok'):
        print(f"    Error: {r.get('error', r.get('data'))}")
PYEOF
```

### Check Canvas Output
```bash
cat "$(ls ~/jarvis-voice/data/canvas/page_* | tail -1)"
```

---

## Step 6: Checklist Before Finalizing

- [ ] Tested each tool individually to verify return structure
- [ ] Extract rules use correct field names (not assumed)
- [ ] Stash save uses `text` param (not `content`) or `file_path` for local files
- [ ] SSH uses `action: "run"` and extracts from `stdout`
- [ ] Variables have defaults where appropriate
- [ ] Used `url_domain` transform for folder paths (e.g., `Workflows/Type/${url_domain}`)
- [ ] Required steps will abort on failure
- [ ] Optional steps have `"required": false` and `"on_fail": "continue"`
- [ ] Steps that may fail (crawl, screenshot) are optional with fallback data
- [ ] `llm_prompt` includes all needed `${variables}` for context
- [ ] `llm_prompt` instructs LLM to use actual values, not output `${var}` syntax
- [ ] Canvas title uses folder structure (e.g., `Workflows/Category/${topic}`)
- [ ] Set `"allow_workflow_tool": false` for explicit/API/scheduled-only workflows that Jarvis must not choose through the `workflow` meta-tool
- [ ] Tested full workflow via CLI
- [ ] Checked final output (canvas, stash, etc.)

---

## Existing Workflow Examples

| Workflow | Command | Key patterns |
|----------|---------|--------------|
| `bookmark_search.json` | `* <query>` | Explicit prefix trigger, Firefox bookmark lookup |
| `crypto_market_report.json` | `/crypto [coins]` | Multiple crypto_price calls, LLM formatting |
| `daily_status.json` | `/status` | Static variables, nested extracts, multi-tool dashboard |
| `daily_status_visual.json` | `/status_visual` | Same crypto pipeline as `daily_status` (`crypto_chart`, fenced `crypto-chart` blocks); `generate_image` + `image_ref` at top of canvas |
| `deep_dive.json` | `/dive <url>` | screenshot_url, stash file kind, vision as primary source, resilient crawl, url_domain transform, folder-structured canvas |
| `deep_research.json` | `/research <topic>` | Search, for_each crawl, validation |
| `github_ai_radar_daily.json` | `/github_ai_radar` | Brave search and LLM context, optional YouTube result, rolling Canvas update |
| `jarvis_self_check.json` | `/jarvis_self_check` | Local system health, deduplicated alerts, full Canvas update |
| `memory_scan.json` | `/memory_scan` | Mode-aware memory dedupe, stash report, labeled Canvas report |
| `quick_note.json` | `/note <text>` | Simple text capture, remember, canvas |
| `serpapi_search.json` | `/serpapi <query>` | SerpApi search, stash text export, Canvas summary |
| `server_health_check.json` | `/health [host]` | Default value, ssh_remote, get_time |
| `url_ingest.json` | `/url_ingest <url>` | crawl_url, stash, text_summarizer, manage_intel (auto_ingest), search_memory |
| `weather_watch.json` | `/weather_watch` | Environment-backed default location, condition branching, alerts, Canvas |
| `web_archive.json` | `/archive <url>` | URL extraction, crawl_url transform, stash save |
| `youtube_ingest.json` | `/youtube_ingest <url>` | Video and transcript ingestion, fact extraction, keywords, Canvas briefing |
| `youtube_research.json` | `/youtube_research <url> [notes]` | youtube_transcript, stash read, text_summarizer, canvas |
| `yt_dlp_release_watch.json` | `/yt_dlp_release_watch` | release_watch state, git_release_notes, deduplicated alert, acknowledgement |

### Best Practice Example: deep_dive.json

The `deep_dive.json` workflow demonstrates several best practices:

1. **Vision as primary data source** - Screenshot with AI analysis works even when crawling is blocked
2. **Resilient design** - `crawl_url` is optional (`required: false, on_fail: continue`)
3. **Stash local files** - Uses `kind: "file"` to stash screenshots from `/tmp`
4. **Domain transform** - `url_domain` variable for canvas folder organization
5. **Canvas folder structure** - `Workflows/Deep Dive/${url_domain}`
6. **LLM prompt clarity** - Explicitly tells LLM to use actual values, not placeholder syntax

---

## Full Documentation

See [docs/WORKFLOW_ORCHESTRATION.md](../../docs/WORKFLOW_ORCHESTRATION.md) for complete reference.
