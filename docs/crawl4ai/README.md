# Crawl4AI Integration

> Advanced web crawling and screenshot capabilities for Jarvis

Crawl4AI is a self-hosted web crawler with powerful features for extracting content from any webpage, including JavaScript-heavy and protected sites.

## Quick Links

- **API Docs**: https://docs.crawl4ai.com/api/parameters/
- **Your Instance**: https://a40k0kw088sw8s84kcw88wk0.bigsk1.com
- **OpenAPI Spec**: https://a40k0kw088sw8s84kcw88wk0.bigsk1.com/openapi.json

---

## Current Jarvis Tools

### 1. `crawl_url` - Web Content Extraction

Crawls URLs and returns clean markdown content.

```bash
# Basic crawl
./orchestrator/orchestrator_v2.py cloud "crawl https://example.com and summarize it"

# With stealth mode for protected sites
./orchestrator/orchestrator_v2.py cloud "crawl https://news.ycombinator.com with stealth mode"
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `url` | string | Single URL to crawl |
| `urls` | array | Multiple URLs to crawl |
| `stealth` | bool | Enable bot detection bypass |
| `wait_for` | string | CSS selector to wait for |
| `wait_for_js` | bool | Wait for JS to fully load |
| `js_code` | string | JavaScript to execute |
| `css_selector` | string | Focus on specific element |
| `exclude_tags` | array | Tags to exclude (default: nav, footer, aside) |

### 2. `screenshot_url` - Visual Page Capture + AI Analysis

Takes screenshots and optionally analyzes with vision AI. **Bypasses anti-bot measures!**

```bash
# Screenshot only
./orchestrator/orchestrator_v2.py cloud "screenshot https://example.com"

# Screenshot + vision analysis (the magic!)
./orchestrator/orchestrator_v2.py cloud "screenshot rotten tomatoes minecraft movie and tell me the scores"
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `url` | string | URL to screenshot |
| `analyze` | bool | Run vision AI on screenshot |
| `question` | string | What to ask about the image |
| `wait` | number | Seconds to wait before capture |
| `save_path` | string | Custom save location |

**Why this is powerful:**
- Screenshots render the actual page (like a human sees it)
- Works on any site regardless of anti-bot measures
- Vision AI can read text, identify elements, extract data
- 20MB BMP → 93KB JPEG auto-conversion for vision APIs

---

## Configuration

### Environment Variables

Add to `config/cloud.env` and `config/local.env`:

```bash
# Crawl4AI - Advanced web crawler
CRAWL4AI_URL=https://your-instance.com
CRAWL4AI_USER=admin
CRAWL4AI_PASS=your-password
CRAWL4AI_API_KEY=your-api-key
```

---

## API Endpoints Reference

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/crawl` | POST | Crawl URLs, return markdown |
| `/md` | POST | Simple markdown extraction |
| `/screenshot` | POST | Full-page screenshot |
| `/pdf` | POST | Generate PDF of page |
| `/html` | POST | Get processed HTML |
| `/execute_js` | POST | Run JavaScript on page |

### Monitoring Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/monitor/health` | GET | System health snapshot |
| `/monitor/requests` | GET | Active/completed requests |
| `/monitor/browsers` | GET | Browser pool status |
| `/monitor/logs/errors` | GET | Recent errors |
| `/monitor/endpoints/stats` | GET | Endpoint statistics |
| `/metrics` | GET | Prometheus metrics |

### LLM Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/llm/job` | POST | Submit LLM extraction job |
| `/llm/job/{task_id}` | GET | Check job status |
| `/ask` | GET | Query crawl4ai docs (BM25 search) |

---

## Debugging Commands

```bash
# Set auth variables
AUTH="admin:your-password"
BASE="https://your-instance.com"
KEY="your-api-key"

# System health
curl -s -u "$AUTH" "$BASE/monitor/health" | jq '.'

# Recent requests
curl -s -u "$AUTH" "$BASE/monitor/requests?status=all&limit=10" | jq '.'

# Browser pool
curl -s -u "$AUTH" "$BASE/monitor/browsers" | jq '.'

# Error logs
curl -s -u "$AUTH" "$BASE/monitor/logs/errors?limit=20" | jq '.'

# Endpoint stats
curl -s -u "$AUTH" "$BASE/monitor/endpoints/stats" | jq '.'

# Force cleanup
curl -s -u "$AUTH" -X POST "$BASE/monitor/actions/cleanup" | jq '.'

# Restart browser
curl -s -u "$AUTH" -X POST "$BASE/monitor/actions/restart_browser" \
  -H "Content-Type: application/json" \
  -d '{"sig": "permanent"}' | jq '.'
```

---

## Advanced Features to Explore

### ✅ Implemented

- [x] Basic crawling with markdown extraction
- [x] Stealth mode (bot detection bypass)
- [x] Screenshot capture
- [x] Vision AI analysis of screenshots
- [x] Wait conditions (CSS selector, networkidle)
- [x] Tag exclusion
- [x] CSS selector focus

### 🔮 Future Possibilities

These features are available in crawl4ai but not yet integrated:

#### Deep Crawling
Automatically follow links and crawl entire sites.
```json
{
  "urls": ["https://example.com"],
  "crawler_config": {
    "deep_crawl_strategy": {
      "max_depth": 3,
      "max_pages": 100
    }
  }
}
```

#### LLM Extraction
Use GPT/Claude to extract structured data from pages.
```json
{
  "url": "https://example.com",
  "q": "Extract all product names and prices",
  "schema": "{ \"products\": [{ \"name\": \"string\", \"price\": \"number\" }] }",
  "provider": "openai/gpt-4o"
}
```
*Note: Requires OPENAI_API_KEY configured in crawl4ai docker*

#### PDF Generation
Generate PDFs of web pages.
```json
{
  "url": "https://example.com",
  "output_path": "/output/page.pdf"
}
```

#### JavaScript Execution
Run custom JavaScript on pages.
```json
{
  "url": "https://example.com",
  "scripts": [
    "document.querySelector('.modal-close')?.click()",
    "await new Promise(r => setTimeout(r, 1000))",
    "document.body.innerText"
  ]
}
```

#### Hooks
Custom Python code that runs at various points in the crawl lifecycle.
```json
{
  "urls": ["https://example.com"],
  "hooks": {
    "code": {
      "on_page_loaded": "page.screenshot(path='/tmp/debug.png')"
    },
    "timeout": 30
  }
}
```

#### Content Filtering
Different strategies for cleaning content.
```json
{
  "url": "https://example.com",
  "f": "fit",  // or "raw", "bm25", "llm"
  "q": "query for bm25/llm filtering"
}
```

---

## Troubleshooting

### Protected Sites (RT, IMDB, etc.)

These sites have aggressive anti-bot measures:

1. **Try `crawl_url` with `stealth: true`** - may work for some sites
2. **Use `screenshot_url` with `analyze: true`** - vision AI reads the rendered page
3. **Use `brave_search`** - gets snippets from search results

### Large Screenshots

Screenshots are auto-converted:
- BMP → JPEG (much smaller)
- Resized to max 2000px (for vision APIs)
- Quality 85% (good balance)

### API Parameter Names

The crawl4ai REST API uses:
- `browser_config` - Browser settings (stealth, user agent, etc.)
- `crawler_config` - Crawl settings (wait conditions, selectors, etc.)

**NOT** `crawler_params` (common mistake).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Jarvis                               │
├─────────────────────────────────────────────────────────────┤
│  crawl_url.py          │  screenshot_url.py                 │
│  - Markdown extraction │  - Full-page capture               │
│  - Stealth mode        │  - Vision AI analysis              │
│  - Content filtering   │  - Auto-resize for APIs            │
└────────────┬───────────┴────────────┬───────────────────────┘
             │                        │
             ▼                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    Crawl4AI REST API                         │
│         https://a40k0kw088sw8s84kcw88wk0.bigsk1.com         │
├─────────────────────────────────────────────────────────────┤
│  /crawl      │  /screenshot  │  /pdf     │  /execute_js     │
│  /md         │  /html        │  /llm/job │  /monitor/*      │
└─────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Chromium Browser Pool                      │
│  - Permanent browser (always running)                        │
│  - Hot pool (recently used, fast reuse)                      │
│  - Cold pool (idle, lower memory)                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Related Files

- `skills/crawl_url.py` - Crawl tool implementation
- `skills/crawl_url.tool.json` - Crawl tool definition
- `skills/screenshot_url.py` - Screenshot tool implementation
- `skills/screenshot_url.tool.json` - Screenshot tool definition
- `config/cloud.env` - Configuration (CRAWL4AI_* vars)
- `config/local.env` - Local mode configuration

---

## Changelog

### 2024-12-22
- Initial integration with crawl4ai
- `crawl_url` tool with stealth mode, wait conditions
- `screenshot_url` tool with vision AI analysis
- Fixed API parameter names (`crawler_config` not `crawler_params`)
- Auto image conversion (BMP→JPEG, resize for vision APIs)

