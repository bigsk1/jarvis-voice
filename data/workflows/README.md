# Workflow definitions (`data/workflows/`)

JSON files here are **deterministic pipelines**: fixed tool order, optional LLM only for `llm_prompt` / validation / branching. The orchestrator loads `*.json`, matches **explicit** triggers like `/note`, resolves **variables**, substitutes **`${...}`** in params, runs **steps** in order.

Use this document as the **format contract** when authoring or editing workflows (humans and agents). Implementation details live in `orchestrator/pipeline_executor.py` (`_extract_workflow_variables`, `_resolve_params`) and `orchestrator/workflow_loader.py`.

---

## Top-level object (required shape)

| Field | Type | Notes |
|--------|------|--------|
| `id` | string | Unique workflow id; required or file is skipped. |
| `steps` | array | Non-empty; each step is an object with at least `step` (int), `tool` (string). |
| `enabled` | boolean | If `false`, loader ignores the file. Default treated as true when missing. |
| `name` | string | Display / documentation. |
| `description` | string | Display / documentation. |
| `version` | string | Optional; informational. |
| `triggers` | object | At minimum use `explicit`: list of command strings (e.g. `"/archive"`). |
| `variables` | object | Optional; see **Variables** below. |
| `success_speech` | string | Resolved with `${variables}` when workflow completes. |
| `abort_speech` | string | Optional; used when workflow aborts. |

**Triggers:** Production matching is **explicit-only** by default (slash commands). `patterns` / `keywords` exist in the schema but are not the normal path; prefer `explicit`. Aliases like `/status-visual` and `/status_visual` are normalized by the router—define the forms you care about in `explicit`.

---

## Variables (exact formats)

After load, the runtime always has at least: `query`, `topic`, `content` (same as `topic`), `workflow_id`, `timestamp`. Your `variables` block **adds or overrides** named keys used as `${name}` in steps.

### 1. Static primitives

Any JSON string, number, or boolean is copied as-is:

```json
"variables": {
  "timeout_seconds": 30,
  "dry_run": false,
  "label": "example-label"
}
```

Use this for **non-sensitive defaults** that are not user- or deployment-specific.

### 2. From the user query (`from`: `"query"`)

Object form:

```json
"variables": {
  "topic": { "from": "query", "extract": "main_subject" },
  "url": { "from": "query", "extract": "url" },
  "host": { "from": "query", "extract": "main_subject", "default": "vps2" }
}
```

Supported **`extract`** values:

| `extract` | Meaning |
|-----------|---------|
| `main_subject` | Text after the command (the routed “topic”). |
| `url` | First URL-like substring in the topic (protocol added if missing). |
| `short_title` | Short title derived from topic (may use LLM where configured). |
| `first_words` | First `max_words` words from topic, joined with `_` (see `max_words`, default 4). |

If extraction yields empty and **`default`** is set, `default` is used.

### 3. From environment (`from`: `"env"`)

Reads **`os.environ`** at run time (values come from `config/cloud.env`, `config/local.env`, or the shell, depending on how Jarvis is started):

```json
"variables": {
  "location": {
    "from": "env",
    "key": "JARVIS_DEFAULT_LOCATION",
    "default": "City, Region"
  }
}
```

**Portable workflows:** For **default city/region** used by weather and similar tools, prefer this pattern with **`JARVIS_DEFAULT_LOCATION`** so forks set their own value in env—not a hardcoded city in JSON. Replace `"City, Region"` with whatever safe fallback you want when the env var is unset.

Optional: `key` defaults to the variable name if omitted (`"location": { "from": "env" }` uses env var `location`—usually you want an explicit `key`).

### 4. Static inline (`from`: `"static"`)

```json
"variables": {
  "mode": { "from": "static", "value": "summarize" }
}
```

### 5. Transforms (second pass; `from` references another variable)

The orchestrator runs a **second pass** for entries that have **`transform`**. Then **`from`** must be the name of another variable already resolved (often another key in the same `variables` block):

```json
"variables": {
  "url": { "from": "query", "extract": "url" },
  "url_domain": { "from": "url", "transform": "domain", "default": "unknown" }
}
```

Supported **`transform`** values: `domain`, `lowercase`, `uppercase`, `strip`.

---

## Substitutions in steps (`${…}`)

- `${var}` — simple variable.
- `${nested.path}` — dotted lookup into the variables dict (e.g. fields merged from tool results).
- `${arr[:N]}` — slice notation where implemented for arrays.

Resolve rules and templating: see `_resolve_variable` / `_resolve_template_string` in `orchestrator/pipeline_executor.py`.

---

## Steps (minimal expectations)

Each step typically includes:

- `step` — integer order.
- `tool` — registered tool name.
- `action` — for multi-action tools (e.g. `stash`, `canvas`).
- `params` — object; values may contain `${variables}` strings.
- `extract` — maps **new variable names** to paths under **`result.data`** (paths must **not** use a `data.` prefix).
- `output_var` — optional; stores raw tool payload under that variable name.
- `required` — default true; if false and step fails, behavior depends on `on_fail`.
- `on_fail` — e.g. `"continue"` for optional steps.
- `llm_prompt` — optional; LLM fills params (uses tokens).

Authoritative step recipes and tool return shapes: **[AGENTS.md](AGENTS.md)**.

---

## Authoring checklist (agents)

1. Valid JSON only—no `//` comments inside JSON files.
2. Include **`id`** and a non-empty **`steps`** array or the loader skips the file.
3. Use **`extract`** paths relative to tool **`data`** (never prefix with `data.`).
4. For **`llm_prompt`** steps that produce user-visible markdown, instruct the model to emit **real values**, not literal `${var}` text.
5. Prefer **`JARVIS_DEFAULT_LOCATION`** (env-backed `variables`) for default geography instead of embedding a specific city in shared workflow JSON.

---

## Quick Start

1. Add a new `something.json` under this folder.
2. Copy an existing workflow closest to your use case, then edit **`id`**, **`triggers.explicit`**, **`variables`**, **`steps`**.
3. Set **`enabled`: true**.
4. Run via CLI or Web UI using the explicit command.

---

## Minimal skeleton (copy and rename)

```json
{
  "id": "example_pipeline",
  "name": "Example pipeline",
  "description": "Replace with real description",
  "version": "1.0",
  "enabled": true,
  "triggers": {
    "explicit": ["/example"],
    "patterns": [],
    "keywords": []
  },
  "variables": {
    "subject": { "from": "query", "extract": "main_subject" },
    "location": {
      "from": "env",
      "key": "JARVIS_DEFAULT_LOCATION",
      "default": "City, Region"
    }
  },
  "steps": [
    {
      "step": 1,
      "tool": "get_time",
      "params": {},
      "required": true,
      "description": "Example step"
    }
  ],
  "success_speech": "Done with ${subject}.",
  "abort_speech": "Example workflow aborted."
}
```

---

## Current workflows

| File | Command | Description |
|------|---------|-------------|
| `web_archive.json` | `/archive <url>` | Fetch URL, save to stash, create canvas summary |
| `deep_research.json` | `/research <topic>` | Multi-source research with validation |
| `quick_note.json` | `/note <text>` | Quick note to memory and canvas |
| `server_health_check.json` | `/health <host>` | SSH health check on remote server |
| `daily_status.json` | `/status` | Weather, crypto (7d charts on Canvas), stocks, alerts, system health dashboard |
| `daily_status_visual.json` | `/status_visual` (also `/status-visual`, `/status-image`, `/daily-visual`) | Same as `/status` (including crypto charts) plus `generate_image` and dashboard image at top of Canvas |
| `weather_watch.json` | `/weather_watch` | Default-location weather watch with canvas report and condition-specific alerts |
| `crypto_market_report.json` | `/crypto [coins]` | Crypto prices with canvas report |
| `youtube_research.json` | `/youtube_research <url> [notes]` | Download transcript, summarize, keywords, canvas study notes |
| `youtube_ingest.json` | `/youtube_ingest <url>` | Download video + transcript, extract important facts/keywords, create canvas briefing |
| `url_ingest.json` | `/url_ingest <url>` | Fetch any URL, create intel file, ingest to memory for RAG queries |
| `memory_scan.json` | `/memory_scan` | Run memory_deduper analyze mode and save readable dedupe report to stash + canvas |
| `deep_dive.json` | `/deep_dive <topic or url>` | Screenshot + crawl + comprehensive canvas analysis with pros/cons, links |
| `serpapi_search.json` | `/serpapi <query>` | Run SerpApi search, save `.txt` export to stash, create canvas summary report |

---

## Stash `kind` values

The `stash` tool accepts:

- `text` — use param `text`
- `json` — use param `json`
- `base64` — use param `data`
- `url` — use param `url`
- `file` — use param `file_path` (screenshots and local artifacts)

---

## Canvas folder titles

```json
"params": {
  "title": "Workflows/Deep Dive/${url_domain}",
  "tags": ["workflow-type", "${url_domain}"]
}
```

---

## Resilient optional steps

```json
{
  "step": 4,
  "tool": "crawl_url",
  "params": { "url": "${url}" },
  "required": false,
  "on_fail": "continue",
  "description": "Optional crawl; pipeline continues if blocked"
}
```

---

## Extract paths (tool results)

Paths in **`extract`** are relative to the tool’s **`data`** object.

CORRECT:

```json
"extract": { "temperature": "temperature", "cpu": "cpu.total_percent" }
```

WRONG:

```json
"extract": { "temperature": "data.temperature" }
```

---

## Further reading

- Architecture and features: [docs/WORKFLOW_ORCHESTRATION.md](../../docs/WORKFLOW_ORCHESTRATION.md)
- Tool payloads and copy-paste patterns: [AGENTS.md](AGENTS.md)
