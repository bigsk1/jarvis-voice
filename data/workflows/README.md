# Workflow definitions (`data/workflows/`)

JSON files here are **deterministic pipelines**: fixed tool order, optional LLM only for `llm_prompt` / validation / branching. The orchestrator loads `*.json`, matches **explicit** triggers like `/note`, resolves **variables**, substitutes **`${...}`** in params, runs **steps** in order.

Use this document as the **format contract** when authoring or editing workflows (humans and agents). Implementation details live in `orchestrator/pipeline_executor.py` (`_extract_workflow_variables`, `_resolve_params`) and `orchestrator/workflow_loader.py`.

Private workflows can live in `data/workflows/personal/*.json`. That folder is gitignored for JSON workflow files, but loaded by the same workflow APIs and scheduler. Personal workflows with the same `id` as a shared workflow override the shared definition locally.

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
| `allow_workflow_tool` | boolean | Optional; defaults to `true`. Set `false` to block Jarvis from discovering, describing, or running this recipe through the autonomous `workflow` meta-tool while preserving explicit commands, API execution, and scheduled tasks. |
| `triggers` | object | At minimum use `explicit`: list of command strings (e.g. `"/archive"`). |
| `variables` | object | Optional; see **Variables** below. |
| `success_speech` | string | Resolved with `${variables}` when workflow completes. |
| `abort_speech` | string | Optional; used when workflow aborts. |

**Triggers:** Production matching is **explicit-only** by default (slash commands). `patterns` / `keywords` exist in the schema but are not the normal path; prefer `explicit`. Matching is exact prefix (`startswith`) with no hyphen/underscore normalization—list every alias you care about in `explicit` (e.g. both `/status-visual` and `/status_visual` if you want both).

Normal orchestration can also discover workflows through the compact
`workflow(search|describe|run)` meta-tool. This does not enable keyword/pattern
trigger matching: the meta-tool searches workflow metadata, returns only
currently runnable recipes, and requires an exact workflow id for execution.
Shared and `personal/` workflows participate equally, including personal
same-id overrides.

Disabling the `workflow` tool in its manifest, the active tool profile, or the
Web blocked-tools list disables this **autonomous meta-tool path** for that
surface. It does not disable direct slash commands or scheduled workflow tasks.

For a per-workflow boundary, set top-level `"allow_workflow_tool": false`.
The recipe remains enabled for deliberate execution through an explicit slash
command, the workflow API, or a scheduled task, but the `workflow` meta-tool
will not return it from search and will reject exact describe/run attempts.
This is appropriate for personal or side-effecting recipes that Jarvis should
never choose on its own.

---

## Runtime mode and shared artifacts

Workflow JSON is normally **mode-neutral**. A workflow does not need separate
cloud/local files unless the actual step behavior is different. It runs in the
mode of the Jarvis process or request that executed it.

Mode-aware tools should label the source they used when output is saved for
humans. For example, `/memory_scan` scans the active memory DB:

- cloud mode: `data/jarvis_memory.db`
- local mode: `data/jarvis_memory_local.db`

If the Web UI/API session is switched to local and `/memory_scan` runs, the
workflow should save a Canvas report that says it scanned the local memory DB.
If it runs in cloud mode, the report should say cloud memory DB.

Shared artifact surfaces are not split by cloud/local mode by default:

- Canvas pages are shared under `data/canvas/*.json`. The Canvas server has a
  startup mode for config, auth, URLs, and health reporting, but page storage is
  mode-agnostic.
- Stash uses one root from `STASH_DIR`, normally `data/stash`. If `STASH_DIR`
  is intentionally pointed somewhere else, all stash readers and writers should
  resolve that same root.
- Docs and workflow JSON files are repo files, not mode-scoped data stores.

Authoring rule: when a workflow reads mode-scoped data such as memory,
intelligence, or provider-specific runtime config, include the mode/source/path
in the tool result and in any saved Canvas or stash report. Do not create
duplicate workflow files just to rename cloud vs local output.

---

## Variables (exact formats)

After load, the runtime always has at least: `query`, `topic`, `content` (same as `topic`), `workflow_id`, `timestamp` (ISO-8601 for document metadata), and `filename_timestamp` (`YYYYMMDD-HHMMSS` for filesystem-safe artifact names). Your `variables` block **adds or overrides** named keys used as `${name}` in steps.

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
  "stash_ref": { "from": "query", "extract": "stash_ref", "default": "" },
  "attachment_filename": { "from": "query", "extract": "attachment_filename", "default": "" },
  "host": { "from": "query", "extract": "main_subject", "default": "vps2" }
}
```

Query extraction supports `main_subject`, `url`, `stash_ref`,
`attachment_filename`, `short_title`, `first_words` (with optional `max_words`,
default `4`), and `location_date_context`. `stash_ref` accepts a direct
`stash://...` value or the structured stash reference included with a Web
attachment.

Supported **`extract`** values:

| `extract` | Meaning |
|-----------|---------|
| `main_subject` | Text after the command (the routed “topic”). |
| `url` | First URL-like substring in the topic (protocol added if missing). |
| `stash_ref` | First `stash://space_id/file_id` reference in the topic or structured Web attachment context. |
| `attachment_filename` | `Filename:` value from a structured Web attachment context block. |
| `short_title` | Short title derived from topic (may use LLM where configured). |
| `first_words` | First `max_words` words from topic, joined with `_` (see `max_words`, default 4). |
| `location_date_context` | Reusable nested planning context containing an explicit location, normalized optional target date, and their sources. Default-location fallback and forecast-window fields are opt-in. |

If extraction yields empty and **`default`** is set, `default` is used.

For a reusable location/date context, keep the result nested instead of
injecting workflow-specific top-level variables:

```json
"variables": {
  "planning_context": {
    "from": "query",
    "extract": "location_date_context",
    "allow_default_location": true,
    "forecast_horizon_days": 10
  }
}
```

Use `${planning_context.location}`, `${planning_context.location_source}`,
`${planning_context.target_date}`, and `${planning_context.target_date_source}`
in later steps. When `forecast_horizon_days` is present, the context also
contains `forecast_eligible`, `forecast_skip_reason`, `forecast_window_start`,
`forecast_window_end`, and the bounded `forecast_horizon_days` value. The
forecast horizon is clamped to the weather tool's supported 1–10 day range.

`allow_default_location` defaults to `false`. Set it to JSON boolean `true`
only when the recipe is intentionally allowed to fall back to the active
mode's `JARVIS_DEFAULT_LOCATION`, then `JARVIS_DEFAULT_POSTAL_CODE`. Workflows
that require an explicit destination should omit it. Omitting
`forecast_horizon_days` keeps the helper reusable for non-weather workflows and
returns only location/date context fields.

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

Supported **`transform`** values: `domain`, `lowercase`, `uppercase`, `strip`,
and `kebab` (lowercase words joined by `-`).

---

## Substitutions in steps (`${…}`)

- `${var}` — simple variable.
- `${nested.path}` — dotted lookup into the variables dict (e.g. fields merged from tool results).
- `${arr[0]}` — list index lookup.
- `${nested.list[0].field}` — indexed lookup inside a dotted path.
- `${arr[:N]}` — slice notation for arrays.

Resolve rules and templating: see `_resolve_variable` / `_resolve_template_string` in `orchestrator/pipeline_executor.py`.

Bracket syntax is only special inside workflow variable expressions such as `${results[0].url}` and `extract` paths such as `results[0].url`. Literal markdown/text sent to tools or Canvas is not parsed as a path just because it contains brackets or parentheses.

---

## Steps (minimal expectations)

Each step typically includes:

- `step` — integer order.
- `tool` — registered tool name.
- `action` — for multi-action tools (e.g. `stash`, `canvas`).
- `params` — object; values may contain `${variables}` strings.
- `extract` — maps **new variable names** to paths under **`result.data`** (paths must **not** use a `data.` prefix).
- `output_var` — optional; stores step output under that variable name. If a built-in transform creates a workflow-friendly value with the same name, that value is preserved instead of being overwritten by the raw payload.
- `for_each` — repeats a step over an array such as `${search_results.urls[:5]}`.
- `retry.max_attempts` — when explicitly set on a `for_each` step, caps the number of input items attempted; the workflow-wide `max_total_retries` still caps accumulated failed attempts.
- `required_success_count` — for a `for_each` producer, stop after this many successful/validated results (default `1`).
- `process_all` — for a `for_each` consumer, process every input item instead of stopping after one success.
- `validated_output_var` — stores the successful/validated outputs from a `for_each` producer under an explicit semantic variable such as `validated_articles`.
- `required` — default true. If explicitly false, an unavailable tool does not
  block workflow admission: the step is recorded as skipped and the run is
  marked degraded. If the available tool executes and fails, behavior depends
  on `on_fail`.
- `on_fail` — e.g. `"continue"` for optional steps.
- `llm_prompt` — optional; LLM fills params (uses tokens).
- `llm_variable_max_chars` — optional per-step cap for each structured `${...}` value inserted into `llm_prompt`; defaults to `3000` and is clamped to `500`–`50000`. Raise it only for bounded inputs whose complete rows must reach the helper model.
- Workflow-level `disable_server_side_tools` — optional boolean; when true, workflow LLM helper calls for `llm_prompt`, validation, branching, or completion speech run without provider-native search/tools. Explicit workflow steps such as Brave search, crawl, or other Jarvis tools still run normally.

Before any execution surface runs the recipe, every required step tool must
exist in the effective active-mode registry and must not be excluded for that
surface. Conditional steps remain required unless they explicitly set
`"required": false`. A manifest-disabled, profile-disabled,
configuration-unavailable, or Web/request-blocked optional tool is skipped
without being called; the workflow result reports `degraded: true` and lists it
under `optional_tools_skipped`, and completion speech names the skipped tools.
Required tools remain strict, workflows never
force-enable or substitute tools, and recursive steps with `"tool": "workflow"`
are always rejected. If one tool appears in both required and optional steps,
it remains required.

Authoritative step recipes and tool return shapes: **[AGENTS.md](AGENTS.md)**.

---

## Authoring checklist (agents)

1. Valid JSON only—no `//` comments inside JSON files.
2. Include **`id`** and a non-empty **`steps`** array or the loader skips the file.
3. Use **`extract`** paths relative to tool **`data`** (never prefix with `data.`).
4. On validated `for_each` source steps, set **`validated_output_var`** explicitly; do not rely on tool-specific compatibility behavior.
5. When a later `for_each` step must save/process every validated result, set **`process_all: true`**.
6. For **`llm_prompt`** steps that produce user-visible markdown, instruct the model to emit **real values**, not literal `${var}` text.
7. Prefer **`JARVIS_DEFAULT_LOCATION`** (env-backed `variables`) for default geography instead of embedding a specific city in shared workflow JSON.
8. Set workflow-level **`disable_server_side_tools: true`** when deterministic source/tool steps already provide the facts and `llm_prompt` should only extract or synthesize from workflow variables.
9. For search → crawl workflows, keep the search step's **`output_var`** as **`search_results`** so the built-in transform exposes `${search_results.urls[:N]}`.
10. For single URL crawl workflows, use **`output_var: "article"`** when later steps need `${article.content}`, `${article.url}`, or `${article.title}`.
11. For mode-scoped data such as memory or intelligence, expose the active mode/source in the workflow output and in saved Canvas/stash reports.
12. Assume autonomous foreground execution may select the recipe: keep `name`, `description`, explicit triggers, and query-derived variables clear enough for compact metadata search.
13. Set `"allow_workflow_tool": false` when the recipe must remain explicit, API-only, or scheduled-only—especially for personal workflows with sensitive side effects.
14. Make side effects and repeat behavior safe. Autonomous orchestration permits only one started workflow run per request, but scheduled or later explicit runs are independent.
15. Give downstream prompts and artifact steps truthful defaults for values
    produced by optional tools, because an unavailable optional tool can be
    skipped before execution.

---

## Quick Start

1. Add a new `something.json` under this folder.
2. Copy an existing workflow closest to your use case, then edit **`id`**, **`triggers.explicit`**, **`variables`**, **`steps`**.
3. Set **`enabled`: true**.
4. Run via CLI or Web UI using the explicit command.

You can also ask Jarvis normally and let the enabled `workflow` meta-tool find
the recipe. That path waits for completion and returns the workflow result to
the same orchestration turn; it is not a durable background run.

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
| `bookmark_search.json` | `* <query>` | Search Firefox bookmarks using the same prefix as the Firefox address bar |
| `buying_brief.json` | `/buying_brief <product>` (also `/price_compare`) | Compare Google Shopping Light, Amazon, and eBay results with configured localization, optional Stash evidence, and a Canvas recommendation |
| `crypto_market_report.json` | `/crypto [coins]` | Crypto prices with canvas report |
| `daily_status.json` | `/status` | Weather, crypto (7d charts on Canvas), stocks, alerts, system health dashboard |
| `daily_status_visual.json` | `/status_visual` (also `/status_image`, `/daily_visual`) | Same as `/status` (including crypto charts) plus `generate_image` and dashboard image at top of Canvas |
| `deep_dive.json` | `/deep_dive <url>` (also `/dive`) | Screenshot + crawl + comprehensive canvas analysis with pros/cons and links |
| `deep_research.json` | `/research <topic>` | Multi-source research with validation |
| `game_brief.json` | `/game_brief <sport> <team>` (also `/game_recap`, `/sports_brief`) | Create a current game Canvas brief from structured Google Sports details, with optional Brave narrative enrichment |
| `github_ai_radar_daily.json` | `/github_ai_radar` (also `/ai_radar`, `/ai-radar`) | Search for current GitHub AI project signals with Brave MCP, optionally feature a YouTube result, gather Brave LLM Context, and keep one current Canvas page refreshed |
| `jarvis_self_check.json` | `/jarvis_self_check` (also `/self_check`, `/jarvis_health`) | Local Jarvis host health check with deduped alerts and one refreshed Canvas health page |
| `knowledge_snapshot.json` | `/knowledge <topic>` | Search active-mode Memory, Intel, and prior conversations without new web research, then create or refresh one source-attributed Canvas briefing per topic |
| `local_services_compare.json` | `/local_services_compare <service>` (also `/service_compare`) | Compare Google Local Services, Google Local, and bounded Yelp review evidence using the active mode's configured location, optional Stash evidence, and a dated Canvas shortlist |
| `memory_scan.json` | `/memory_scan` (also `/dedupe_memory`) | Run memory_deduper against the active cloud/local memory DB and save a labeled report to stash + canvas |
| `movie_night.json` | `/movie_night <mood, constraints, or favorite movies>` (also `/what_to_watch`, `/movie_picker`) | Use required public Trakt metadata plus optional read-only account recommendations and deterministic watched filtering, TMDB artwork, YouTube trailers, and Brave streaming context to create a dated Canvas shortlist; no Trakt image hotlinking |
| `night_out.json` | `/night_out <occasion or preference>` (also `/date_night`) | Build a date-aware evening plan from an explicit destination or the active mode default location/postal code and bounded local sources; weather runs only when no outing date is given or the parsed date fits the 10-day horizon |
| `upcoming_movie_radar.json` | `/upcoming_movie_radar <genre criteria>` (also `/movie_release_radar`, `/upcoming_movies`) | Explicit/scheduled TMDB-first release radar with required included-genre inference, provider-side genre exclusion, a rolling Canvas page, optional Brave enrichment, public-poster email fields, and sent-ID deduplication after confirmed email delivery |
| `pdf_ingest.json` | `/pdf_ingest <attached PDF, stash ref, or URL>` | Extract a PDF, create a semantic Intel file, ingest it synchronously, and publish a source-attributed Canvas briefing |
| `quick_note.json` | `/note <text>` | Quick note to memory and canvas |
| `serpapi_amazon_search.json` | `/serpapi_amazon <query>` (also `/amazon_search`, `/serpapi`) | Search Amazon, save a normalized Stash export, and create a Canvas comparison report |
| `server_health_check.json` | `/health <host>` | SSH health check on remote server |
| `team_outlook.json` | `/team_outlook <sport> <team>` (also `/season_outlook`) | Resolve one team ID for current games, focused team standings, and roster views, then add optional current news and a Canvas outlook; `football` means American football and `soccer` means association football |
| `trend_reality_check.json` | `/trend_reality_check <topic>` (also `/trend_check`) | Compare topic-specific Google Trends with the seedless Trending Now feed, optional current news, indexed source candidates, and a Canvas assessment |
| `tv_night.json` | `/tv_night <mood, constraints, or favorite shows>` (also `/what_show_to_watch`, `/tv_picker`) | Use required public Trakt TV metadata plus optional read-only account recommendations and deterministic watched filtering, TMDB artwork/series commitment facts, YouTube trailers, and Brave streaming context; episode runtime remains distinct from total commitment |
| `url_ingest.json` | `/url_ingest <url>` | Fetch any URL, create intel file, ingest to memory for RAG queries |
| `vacation_reconnaissance.json` | `/vacation_reconnaissance <location>` (also `/vacation_recon`, `/destination_scout`) | Create a crawl-free weather, attractions, dining, local pulse, image, Stash, and Canvas destination report for a required location |
| `weather_watch.json` | `/weather_watch` (also `/garden_watch`) | Default-location weather watch with canvas report and condition-specific alerts |
| `web_archive.json` | `/archive <url>` | Fetch URL, save to stash, create canvas summary |
| `youtube_ingest.json` | `/youtube_ingest <url>` | Download video + transcript, extract important facts/keywords, create canvas briefing |
| `youtube_research.json` | `/youtube_research <url> [notes]` | Download transcript, summarize, extract keywords, create canvas study notes |
| `yt_dlp_release_watch.json` | `/yt_dlp_release_watch` (also `/yt-dlp-release-watch`) | Check for a stable yt-dlp release, create Canvas release notes, alert once, and acknowledge the handled version |

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

## Built-in transformed output variables

Some tools return large/raw payloads, but workflows usually need a smaller, stable shape. The executor creates these convenience variables automatically and preserves them when they share the same name as `output_var`.

### Search results

Search-like tools, including `mcp_brave_search_brave_web_search`, expose:

```json
{
  "search_results": {
    "urls": ["https://example.com/a", "https://example.com/b"],
    "data": { "results": [] }
  }
}
```

Use this shape for crawl loops:

```json
{
  "step": 1,
  "tool": "mcp_brave_search_brave_web_search",
  "params": { "query": "${topic}", "count": 5 },
  "output_var": "search_results",
  "required": true
},
{
  "step": 2,
  "tool": "crawl_url",
  "for_each": "${search_results.urls[:3]}",
  "output_var": "crawl_attempts",
  "validated_output_var": "validated_articles",
  "required_success_count": 1,
  "on_all_fail": "continue"
}
```

`search_results.urls` is the normalized URL list. `search_results.data` keeps the original search payload for diagnostics or prompt context.

### Single URL crawl results

For a single `crawl_url` step, `output_var: "article"` exposes:

```json
{
  "article": {
    "title": "Page title",
    "content": "Markdown/text content",
    "url": "https://example.com/page",
    "results": []
  }
}
```

Use it for follow-up stash, Canvas, or summarizer steps:

```json
{
  "step": 1,
  "tool": "crawl_url",
  "params": { "url": "${url}" },
  "output_var": "article",
  "required": true
},
{
  "step": 2,
  "tool": "stash",
  "action": "save",
  "params": {
    "kind": "text",
    "text": "${article.content}",
    "name": "archive_${timestamp}.md"
  },
  "required": true
}
```

Do not use `${article.data.results[0].markdown}` for normal workflows. Prefer the flattened `${article.content}` unless you specifically need the raw result array.

---

## Validated multi-step recipes (`validated_output_var`)

Use `validated_output_var` when one repeated step gathers source material and later steps must consume the **validated source payloads**, not the output of an intervening save/export step.

### Contract

- Put `validated_output_var` on the **producer** `for_each` step—for example, `crawl_url`.
- The value is the list of successful outputs that passed the step's `validation`. If no `validation` block is present, successful tool outputs count as validated.
- `output_var` and `validated_output_var` are different:
  - `output_var` receives all loop outputs, including failures and validation failures.
  - `validated_output_var` receives only successful/validated outputs suitable for downstream synthesis.
- Consume the list with `${validated_articles}` (or the exact variable name you chose).
- Do **not** put `validated_output_var: "validated_articles"` on a later `stash`, export, email, or Canvas loop. That would redefine “articles” to mean save receipts or delivery metadata.
- A `crawl_url` loop has a legacy fallback to `validated_articles`, but new workflows must declare the variable explicitly so the data ownership is obvious and works for other producer tools.
- If a producer loop has an explicit `validated_output_var` and gathers zero valid items, the variable is still set to an empty list. In LLM prompts, `${validated_articles}` formats as `[No articles gathered]` so Canvas/Stash/email synthesis does not see a literal unresolved placeholder.

### Correct gather → save → synthesize recipe

```json
{
  "steps": [
    {
      "step": 1,
      "tool": "stash",
      "action": "open_space",
      "params": { "labels": ["research", "${topic}"] },
      "output_var": "research_space",
      "required": true
    },
    {
      "step": 2,
      "tool": "mcp_brave_search_brave_web_search",
      "params": { "query": "${topic}", "count": 5 },
      "output_var": "search_results",
      "required": true
    },
    {
      "step": 3,
      "tool": "crawl_url",
      "for_each": "${search_results.urls[:5]}",
      "output_var": "crawl_attempts",
      "validated_output_var": "validated_articles",
      "validation": {
        "type": "heuristic",
        "heuristic": {
          "min_length": 500,
          "reject_patterns": ["access denied", "subscribe to continue"]
        }
      },
      "required_success_count": 2,
      "on_all_fail": "abort_with_message"
    },
    {
      "step": 4,
      "tool": "stash",
      "action": "save",
      "for_each": "${validated_articles}",
      "process_all": true,
      "params": {
        "space_id": "${space_id}",
        "kind": "text"
      },
      "output_var": "saved_files",
      "required": true
    },
    {
      "step": 5,
      "tool": "canvas",
      "action": "create",
      "params": { "title": "Workflows/Research/${topic}" },
      "llm_prompt": "Summarize these source articles and cite their URLs:\n\n${validated_articles}",
      "required": true
    }
  ]
}
```

In this pattern:

1. `crawl_attempts` is the audit trail of every attempted crawl.
2. `validated_articles` remains the authoritative source material.
3. `search_results.urls` is the normalized URL list used by the crawl step; the raw search payload remains under `search_results.data`.
4. `saved_files` contains stash receipts and never replaces `validated_articles`.
5. `process_all: true` makes the stash step save every validated article. Without it, a `for_each` step defaults to one required success and may stop after the first item.
6. The Canvas LLM receives actual crawl payloads, including article text and URLs—not stash metadata.

### Incorrect pattern

```json
{
  "tool": "stash",
  "action": "save",
  "for_each": "${validated_articles}",
  "validated_output_var": "validated_articles"
}
```

This reassigns `validated_articles` to stash results. A later summarizer can then receive blank article text/URLs and produce a refusal or hallucinated report.

### Choosing loop controls

| Goal | Setting |
|------|---------|
| Try candidates until two good sources are found | `required_success_count: 2` |
| Save/process every item in an already validated list | `process_all: true` |
| Preserve all attempts for diagnostics | `output_var` |
| Preserve only usable source payloads for later LLM synthesis | `validated_output_var` |

Use `process_all` intentionally. It is opt-in so adding a consumer loop does not change the early-stop behavior of existing search/crawl workflows.

---

## Extract paths (tool results)

Paths in **`extract`** are relative to the tool’s **`data`** object.

CORRECT:

```json
"extract": {
  "temperature": "temperature",
  "cpu": "cpu.total_percent",
  "first_url": "results[0].url",
  "all_urls": "results[*].url"
}
```

WRONG:

```json
"extract": {
  "temperature": "data.temperature",
  "first_url": "data.results[0].url"
}
```

Use `results[0].url` for the first item in a returned list. Use `results[*].url` when you want the same field from every item in the list. Missing paths resolve to `None` and are skipped.

---

## Further reading

- Architecture and features: [docs/WORKFLOW_ORCHESTRATION.md](../../docs/WORKFLOW_ORCHESTRATION.md)
- Tool payloads and copy-paste patterns: [AGENTS.md](AGENTS.md)
