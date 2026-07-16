# Workflow Orchestration System

> **Status**: Implemented
> **Purpose**: Deterministic multi-tool workflow execution for repeatable Jarvis tasks
> **Last Updated**: July 12, 2026

---

![workflow-graph](images/workflow-info-graph.jpeg)

[![Jarvis workflow execution lifecycle](diagrams/jarvis-workflow-execution-lifecycle.svg)](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-workflow-execution-lifecycle.html)

Workflows are Jarvis recipes: JSON pipelines that run known tool steps in a fixed order. They are useful when a task should be fast, repeatable, schedulable, and less dependent on an LLM remembering every step.

They are not a second chat system. Chat, the API, scheduled tasks, and direct workflow runs all route through the same workflow loader, tool registry, and pipeline executor.

## Why Workflows Matter

Normal chat orchestration spends tokens on routing context: system prompts, tool definitions, MCP descriptions, tool-selection turns, and growing conversation history. A workflow skips most of that because the tool order is already known.

| Aspect | Normal chat | Workflow |
|--------|-------------|----------|
| Tool selection | LLM chooses each step | JSON defines the steps |
| Tool schemas in prompt | Often many tools | None for deterministic steps |
| Multi-step memory | Conversation-dependent | Variables and step outputs |
| Token usage | High for orchestration | Only helper LLM calls use tokens |
| Scheduling | Query can run, but output target is model-dependent | Recipe can update the same artifact every run |

Only these workflow features use LLM tokens:

- `llm_prompt` for generated content or parameter filling.
- `validation` with `type: "llm"` or `"hybrid"`.
- `condition: "${llm_decides}"`.
- Final speech synthesis when the executor needs a model-generated summary.

If a workflow uses only deterministic tool steps, orchestration itself uses zero LLM tokens.

## Where Workflows Live

The loader reads enabled JSON files from:

- `data/workflows/*.json`
- `data/workflows/personal/*.json`

`data/workflows/personal/*.json` is gitignored for private local recipes. Personal workflows are loaded by the same APIs and scheduler as shared workflows. If a personal workflow has the same `id` as a shared workflow, the personal version overrides it locally.

The loader does not recursively scan arbitrary subfolders. For example, `data/workflows/skill/` and `data/workflows/backup-workflows/` are not loaded unless code explicitly changes `WorkflowLoader._iter_workflow_files()`.

Implementation references:

- `orchestrator/workflow_loader.py`
- `orchestrator/pipeline_executor.py`
- `data/workflows/README.md`
- `data/workflows/AGENTS.md`
- `data/workflows/skill/SKILL.md`

## How Workflows Run

1. A query or scheduled task names a workflow by trigger or id.
2. `WorkflowLoader` loads enabled JSON definitions.
3. `PipelineExecutor` extracts variables from the query.
4. Steps run in order through the normal `ToolExecutor` and shared tool registry.
5. Step outputs become variables for later steps.
6. The response includes `workflow_id`, step results, tools used, usage metadata, and final speech.

Workflow runs are explicit by default. Slash triggers such as `/research` and `/github_ai_radar` are the normal invocation path. Pattern and keyword triggers exist in the schema but are not the safe default because they can hijack ordinary chat.

## Quick Start

Create `data/workflows/my_workflow.json`:

```json
{
  "id": "my_workflow",
  "name": "My Workflow",
  "description": "Search and summarize a topic into Canvas.",
  "enabled": true,
  "version": "1.0",
  "triggers": {
    "explicit": ["/my_workflow"]
  },
  "variables": {
    "topic": { "from": "query", "extract": "main_subject" }
  },
  "steps": [
    {
      "step": 1,
      "tool": "mcp_brave_search_brave_web_search",
      "params": { "query": "${topic}" },
      "output_var": "search_results",
      "required": true,
      "description": "Search the web"
    },
    {
      "step": 2,
      "tool": "canvas",
      "action": "create",
      "params": {
        "title": "Workflows/My Workflow/${topic}",
        "tags": ["workflow", "research"]
      },
      "llm_prompt": "Write a concise Markdown summary from these results:\n\n${search_results}",
      "llm_output_validation": {
        "param": "content",
        "min_length": 200,
        "reject_patterns": ["```", "<html", "<pre", "I don't have"]
      },
      "required": true,
      "description": "Create Canvas summary"
    }
  ],
  "success_speech": "Workflow complete.",
  "abort_speech": "I couldn't complete the workflow."
}
```

Run it:

```bash
cd ~/jarvis-voice
.venv/bin/python ./orchestrator/orchestrator_v2.py cloud "/my_workflow open source AI agents"
```

If the repo `.venv` needs to be rebuilt, use uv:

```bash
cd ~/jarvis-voice
uv sync --dev
```

Fallback only when the repo venv is unavailable:

```bash
source ~/jarvis-venv/bin/activate
./orchestrator/orchestrator_v2.py cloud "/my_workflow open source AI agents"
```

## Top-Level JSON Fields

| Field | Required | Notes |
|-------|----------|-------|
| `id` | Yes | Unique workflow id. Lowercase snake_case is preferred. |
| `name` | Recommended | Display name in UI. |
| `description` | Recommended | Shown in workflow dropdowns and docs. |
| `enabled` | Recommended | `false` disables the workflow without deleting it. Missing is treated as enabled. |
| `version` | No | Informational. |
| `triggers.explicit` | Recommended | Slash commands such as `["/research"]`. |
| `variables` | No | Query/env/static values used by steps. |
| `steps` | Yes | Non-empty list of tool steps. |
| `tool_defaults` | No | Default params per tool in this workflow. |
| `validation_policy` | No | Workflow-wide retry limits such as `max_total_retries`. |
| `disable_server_side_tools` | No | Disables provider-native tools for helper LLM calls only. |
| `success_speech` | No | Resolved with variables on success. |
| `abort_speech` | No | Used when required steps fail. |

## Step Fields

| Field | Notes |
|-------|-------|
| `step` | Integer used for ordering/logging. |
| `tool` | Registered Jarvis tool name. MCP tools use their registered names, such as `mcp_brave_search_brave_web_search`. |
| `action` | Tool action for multi-action tools such as `canvas` or `stash`. |
| `params` | Tool parameters. Supports `${...}` substitutions. |
| `output_var` | Stores successful step output for later steps. Built-in transforms can preserve a workflow-friendly shape. |
| `extract` | Maps new variable names to paths under `result.data`; do not prefix with `data.`. |
| `for_each` | Repeats a step over an array such as `${search_results.urls[:5]}`. |
| `process_all` | For consumer loops, process every input item instead of stopping after the first success. |
| `required_success_count` | For producer loops, stop after this many successful or validated outputs. Default is `1`. |
| `validated_output_var` | Stores only successful/validated loop outputs under a semantic name. |
| `validation` | Heuristic, LLM, or hybrid result validation. |
| `llm_prompt` | Uses the configured provider to generate params, usually `content`. |
| `llm_output_validation` | Validates LLM-filled params before calling the tool. Use it for Canvas content. |
| `condition` | Deterministic condition or `${llm_decides}`. |
| `set_variables_on_success` | Assign variables after a successful step. |
| `set_variables_on_skip` | Assign variables when a condition skips a step. |
| `required` | Defaults to true. If true and the step fails, the workflow aborts unless `on_fail` overrides it. |
| `on_fail` | Use `"continue"` for optional steps. |

## Variables and Substitution

Every workflow starts with:

- `query`
- `topic`
- `content` as an alias of `topic`
- `workflow_id`
- `timestamp`

Variables can come from the query:

```json
"variables": {
  "url": { "from": "query", "extract": "url" },
  "topic": { "from": "query", "extract": "main_subject" },
  "title": { "from": "query", "extract": "short_title" },
  "slug": { "from": "query", "extract": "first_words", "max_words": 4 }
}
```

Variables can come from environment:

```json
"variables": {
  "location": {
    "from": "env",
    "key": "JARVIS_DEFAULT_LOCATION",
    "default": "City, Region"
  }
}
```

Variables can be static:

```json
"variables": {
  "max_items": 5,
  "report_mode": { "from": "static", "value": "daily" }
}
```

Variables can be transformed in a second pass:

```json
"variables": {
  "url": { "from": "query", "extract": "url" },
  "url_domain": { "from": "url", "transform": "domain", "default": "unknown" }
}
```

Supported transforms are `domain`, `lowercase`, `uppercase`, and `strip`.

Supported substitution forms:

- `${topic}`
- `${article.url}`
- `${results[0].url}`
- `${search_results.urls[:5]}`
- Mixed strings such as `Workflows/Research/${topic}`

Bracket syntax is special only inside workflow variable expressions and extract paths. Literal Markdown links in generated Canvas content are not treated as variable paths.

## Built-In Output Shapes

Some tool outputs are normalized into workflow-friendly variables:

- Search tools can expose `${search_results.urls}` when `output_var` is `search_results`.
- `crawl_url` with `output_var: "article"` exposes `${article.content}`, `${article.url}`, and `${article.title}`.
- Repeated crawl/search steps should use `validated_output_var` to preserve the source material for later summarization.

For search to crawl recipes:

```json
{
  "step": 1,
  "tool": "mcp_brave_search_brave_web_search",
  "params": { "query": "${topic}" },
  "output_var": "search_results"
}
```

Then:

```json
{
  "step": 2,
  "tool": "crawl_url",
  "for_each": "${search_results.urls[:5]}",
  "validated_output_var": "validated_articles",
  "required_success_count": 2,
  "validation": {
    "type": "heuristic",
    "heuristic": {
      "min_length": 500,
      "reject_patterns": ["captcha", "access denied", "subscribe to continue"]
    }
  }
}
```

Later Canvas or summarizer steps should consume `${validated_articles}`, not a stash receipt or delivery result.

## Canvas Patterns

Canvas is the main durable visual/report surface for scheduled workflows.

Use the right action:

- `create` creates a new page.
- `append` adds a new section while preserving the existing page.
- `update` replaces the page content and metadata you pass.
- `read` or `list` should be used before an intentional full-page update when the workflow must preserve existing material.

Important safety rules:

- `append` is best for logs and dated entries.
- `update` is best for a single current dashboard page.
- `update` is a full replacement for `content`; pass the complete desired page content.
- Canvas update blocks accidental large content shrink unless `allow_content_shrink: true` is passed.
- If `allow_content_shrink: true` is used, add `llm_output_validation.required_patterns` or deterministic headings so a malformed LLM page does not wipe the report.
- Canvas helpers reject common bad output such as truncated URLs, outer code fences, and HTML wrappers.

For a “create once, update forever” scheduled workflow, use a stable page lookup/read step, a create step guarded by `not_exists`, and an update step that writes the complete current page. This is the pattern used by rolling dashboard workflows such as GitHub AI Radar and Jarvis self-check.

## Scheduled Tasks

Jarvis Memory can schedule either:

- `query` tasks: run a chat-like query through orchestration.
- `workflow` tasks: run a loaded workflow by id.

Workflow scheduled tasks are first-class:

- The workflow selector is populated from loaded shared and personal workflows.
- The UI shows workflow name, id, triggers, required query-derived inputs, and tools.
- If a workflow declares a variable with `extract: "main_subject"`, Workflow Input is required (other `from: "query"` extract types do not set `requires_input`).
- Workflow input is stored as `task_payload.query` and passed to the workflow trigger at runtime.
- If a workflow does not need input, optional input is harmless and can be ignored by the workflow.
- The schedule text field still accepts natural expressions, and the date/time picker fills that field with an exact local timestamp.
- `now`, `right now`, `immediately`, and `asap` parse as immediate one-shot schedules.

The scheduled runner executes workflows through `WorkflowLoader`, `ToolExecutor`, and `PipelineExecutor`. MCP tools are available through the shared MCP-aware registry used by orchestration, so a workflow run after server start should not need a prior chat message to initialize MCP tools.

Notification behavior:

- Email and webhook notification failures are captured as failed notification results.
- Alert-on-failure creation failures are also captured as failed notification results.
- Notification failures should not prevent run finalization, lock release, or later due tasks.

## MCP and Server-Side Tools

Use MCP tools directly as explicit workflow steps when the workflow needs those sources. Example:

```json
{
  "tool": "mcp_brave_search_brave_web_search",
  "params": { "query": "${topic}" }
}
```

`disable_server_side_tools` does not disable explicit workflow steps. It only suppresses provider-native tools during helper LLM calls, such as xAI/OpenAI/Anthropic native search inside `llm_prompt` or validation calls.

Use:

```json
"disable_server_side_tools": true
```

when deterministic workflow steps already gathered the facts and the helper LLM should only synthesize from those variables.

Use:

```json
"disable_server_side_tools": false
```

or omit the field when helper LLM calls may use provider-native tools.

## Validation

Before handing off a workflow change:

```bash
cd ~/jarvis-voice
.venv/bin/python -m json.tool data/workflows/<id>.json >/dev/null
.venv/bin/python data/workflows/skill/skill.py validate data/workflows/<id>.json
.venv/bin/python data/workflows/skill/skill.py check-loader-scope
```

For loader, executor, API, or scheduled-task changes, run focused pytest from the repo venv:

```bash
cd ~/jarvis-voice
.venv/bin/python -m pytest tests/test_workflow_loader.py tests/test_pipeline_executor.py tests/test_scheduled_task_workflow_input.py tests/test_memory_ui_scheduled_workflows.py
```

If `.venv` is missing or stale:

```bash
cd ~/jarvis-voice
uv sync --dev
```

`~/jarvis-venv` is a fallback for local operator scripts, not the default for repo validation when `.venv` is present.

## Current Shared Workflows

The authoritative list is `data/workflows/*.json` plus any private `data/workflows/personal/*.json` files loaded locally. Current shared examples include:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `quick_note.json` | `/note` | Save a note to memory and Canvas. |
| `web_archive.json` | `/archive` | Fetch a URL, stash content, and create a Canvas summary. |
| `deep_dive.json` | `/deep_dive` | Research a URL or topic with validated source gathering. |
| `deep_research.json` | `/research` | Multi-source research with validation and Canvas output. |
| `github_ai_radar_daily.json` | `/github_ai_radar` | Refresh one rolling GitHub AI Radar Canvas page with search, YouTube, and Brave context. |
| `jarvis_self_check.json` | `/jarvis_self_check` | Check host health, create alerts on problems, and update one Canvas health page. |
| `daily_status.json` | `/status` | Weather, crypto, stocks, alerts, and system health dashboard. |
| `daily_status_visual.json` | `/status_visual` | Daily status with generated dashboard image. |
| `weather_watch.json` | `/weather_watch` | Default-location weather watch with Canvas and alerts. |
| `crypto_market_report.json` | `/crypto` | Crypto prices with Canvas report. |
| `server_health_check.json` | `/health` | SSH health check for a remote server. |
| `youtube_research.json` | `/youtube_research` | Transcript-based YouTube study notes. |
| `youtube_ingest.json` | `/youtube_ingest` | Download video/transcript and create a briefing. |

## Authoring Checklist

- Use valid JSON only; no comments.
- Prefer explicit slash triggers.
- Put private local recipes in `data/workflows/personal/*.json`.
- Keep shared workflows portable by reading user-specific defaults from env.
- Use deterministic tool steps before adding `llm_prompt`.
- Validate LLM-generated Canvas content.
- Use `append` for additive logs and `update` for intentional full-page replacement.
- For scheduled workflows, make repeated runs idempotent: update one durable page, append a bounded log, or create clearly dated artifacts.
- For alertable workflows, wire normal `create_alert` steps instead of adding special scheduler-only alert plumbing.
- Run the focused validation commands above before committing.
