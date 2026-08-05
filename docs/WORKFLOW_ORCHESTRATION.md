# Workflow Orchestration System

> **Status**: Implemented
> **Purpose**: Deterministic multi-tool workflow execution for repeatable Jarvis tasks
> **Last Updated**: July 28, 2026

---

![workflow-graph](images/workflow-info-graph.jpeg)

[![Jarvis workflow execution lifecycle](diagrams/jarvis-workflow-execution-lifecycle.svg)](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-workflow-execution-lifecycle.html)

Workflows are Jarvis recipes: JSON pipelines that run known tool steps in a fixed order. They are useful when a task should be fast, repeatable, schedulable, and less dependent on an LLM remembering every step.

They are not a second chat system. Chat, the API, scheduled tasks, direct slash
commands, and the autonomous `workflow` meta-tool share the same workflow
loader, effective tool registry, and pipeline executor.

In this document, **autonomous** has a narrow meaning: Jarvis decides during a
normal chat or voice turn to call the `workflow` meta-tool and select a recipe.
A scheduled workflow is automated, but it is deliberate—the user chose the
workflow and schedule ahead of time. Explicit slash commands and workflow API
calls are deliberate entry points too.

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

If an explicitly invoked workflow uses only deterministic tool steps, workflow
execution itself uses zero LLM tokens. An autonomously selected workflow still
uses the normal router calls needed to discover/select the recipe and synthesize
the final answer, but avoids separate schema-bearing LLM turns for every
component step.

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

1. A slash command, API/scheduled task, or the autonomous `workflow` meta-tool names a workflow by trigger or id.
2. `WorkflowLoader` loads enabled JSON definitions.
3. Runtime availability is checked against the active mode, profile, surface exclusions, and complete component-tool set.
4. `PipelineExecutor` extracts variables from the query.
5. Steps run in order through the normal `ToolExecutor` and shared tool registry.
6. Step outputs become variables for later steps.
7. The response includes `workflow_id`, step results, tools used, usage metadata, and final speech.

Workflow definitions still match explicit slash triggers only by default.
Pattern and keyword triggers exist in the schema but are not used to hijack
ordinary chat. Autonomous selection is a separate, bounded path: Tool RAG may
surface the compact `workflow` tool, which then searches currently runnable
recipes by metadata and requires an exact workflow id before execution.

## Invocation Paths and Disable Boundaries

| Entry point | How it selects | What disables it |
|-------------|----------------|------------------|
| Explicit slash command | `WorkflowLoader.match()` before normal router turns | Disable the workflow JSON or make any component tool unavailable/excluded |
| Workflow API | Exact workflow id/trigger | Disable the workflow JSON or make any component tool unavailable for that API mode |
| Scheduled workflow | Stored workflow id | Disable the task/workflow or make any component tool unavailable at run time |
| Jarvis-chosen chat/voice | `workflow(search → describe? → run)` selected through Tool RAG | Set `"allow_workflow_tool": false` on that workflow; disable/block the `workflow` meta-tool globally; or make a component tool unavailable |

The `workflow` tool is a feature switch for **autonomous workflow selection**,
not a master switch for the entire workflow subsystem. For example, a profile
containing:

```json
{
  "overrides": {
    "workflow": false
  }
}
```

removes autonomous `workflow` calls from the effective registry after restart,
while `/research` and an existing scheduled `deep_research` task remain
available if all of their component tools are still allowed.

For a per-workflow boundary, use:

```json
"allow_workflow_tool": false
```

This removes the recipe from `workflow(search)` and rejects exact
`workflow(describe)` or `workflow(run)` calls. It does not disable the workflow:
explicit slash commands, `POST /api/workflows/{workflow_id}/execute`, and
scheduled workflow tasks can still run it. The field defaults to `true`, so
existing workflow JSON keeps its current behavior when the field is omitted.

Jarvis Web's Settings → Tools blocked list is request/surface-specific. Blocking
`workflow` prevents Web chat from discovering or calling the autonomous
meta-tool; it does not currently hide direct slash workflow commands. Blocking
a component tool, however, makes every workflow that contains that component
unavailable in Web slash suggestions, detail APIs, and execution.

## Tool and Workflow Availability

Tool eligibility follows the normal precedence:

```text
manifest enabled value
        ↓
active profile override wins
        ↓
mode/config/credential availability
        ↓
effective ToolRegistry
        ↓
Web or request exclusions
        ↓
workflow admission
```

Workflow admission is strict:

- Every step tool must exist in the effective registry.
- Optional and conditional steps still count; there is no degraded recipe mode.
- A workflow never force-enables a component or substitutes a different tool.
- Search/list surfaces omit ineligible workflows.
- Slash, API, scheduled, autonomous `run`, and `PipelineExecutor` recheck before execution.
- A workflow cannot recursively call the `workflow` meta-tool.

Tool RAG sync-status JSON files are health markers, not capability catalogs.
Admission uses the live registry/surface view rather than
`data/.tool_sync_status_<mode>.json`.

## Jarvis-Chosen Foreground Execution (`workflow` Meta-Tool)

The meta-tool exposes three actions:

```text
workflow(action=search, query="task description")
workflow(action=describe, workflow_id="exact_id")
workflow(action=run, workflow_id="exact_id", query="required input")
```

Experimental router prompt versions v2-v4 include this routing contract in
their own wording style. When `workflow` is actually available and a recipe
fully matches the user's task, Jarvis searches with the underlying intent and
desired output, confirms an exact currently runnable ID, and starts at most one
run. It may still use a direct tool for a simple action where no recipe adds
needed work. v1 remains the immutable comparison baseline.

Search reads both shared and personal folders, respects personal same-id
overrides, omits recipes with `"allow_workflow_tool": false`, and returns
compact metadata without component schemas. Exact `describe` and `run` calls
recheck that boundary so a known or hallucinated workflow id cannot bypass
search filtering. `run` then revalidates component availability and waits
synchronously for `PipelineExecutor`.

The outer `workflow` call runs in-process, before `ToolExecutor` enters its
subprocess path. Therefore the generic 60-second cloud / 75-second local
subprocess timeout does not cap the complete recipe, and the Web worker has no
separate workflow wall-clock timeout. Each component tool still retains its
normal default or tool-specific timeout, and provider/HTTP calls retain their
own configured timeouts.

Only one workflow **run** may start in a user request. Search and describe may
precede it; missing-input or availability preflight failures do not consume the
run. Once execution starts, the duplicate guard rejects a second workflow run
even if it uses another workflow id. Completion Guard also excludes workflow
turns so a manual/automatic repair cannot replay a completed recipe.

The immediate router follow-up receives a step-aware preview capped at 8,000
characters. It preserves all steps in current shared recipes, including late
Canvas page ids and Stash refs, while omitting the duplicated workflow variables
graph and bounding bulky content. The canonical result remains available to Web
persistence/follow-up extraction.

Jarvis Web emits component tool cards and saves a tool-name-keyed follow-up
projection alongside the nested workflow result. Existing per-tool adapters
preserve actionable Canvas ids, Stash refs, URLs, and bounded summaries;
repeated component tools remain candidate/run lists rather than overwriting one
another. A later user message can therefore read/update a Canvas page or call an
individual follow-up tool without rerunning the recipe.

Workflow-internal LLM usage is merged into the parent turn, including parameter
filling, validation, generated titles/speech, and component tools such as
`text_summarizer` or Stash auto-summary. Component provider/model identity is
retained when a workflow uses a different summary model.

The result also carries bounded workflow purpose, trigger, and query-input
metadata into Intelligence reflection. Positive learning is matched to the
recipe's actual job, not test phrases such as “run the previous workflow.” This
keeps a large existing Intelligence database from disadvantaging a correct
workflow insight merely because the successful test prompt used unusual
orchestration wording.

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
| `allow_workflow_tool` | No | Defaults to `true`. Set `false` to prevent Jarvis from choosing this recipe through `workflow(search/describe/run)` while preserving explicit slash, API, and scheduled execution. |
| `version` | No | Informational. |
| `triggers.explicit` | Recommended | Slash commands such as `["/research"]`. |
| `variables` | No | Query/env/static values used by steps. |
| `steps` | Yes | Non-empty list of tool steps. |
| `tool_defaults` | No | Default params per tool in this workflow. |
| `validation_policy` | No | Workflow-wide retry limits such as `max_total_retries`. |
| `disable_server_side_tools` | No | Disables provider-native tools for helper LLM calls only. |
| `success_speech` | No | Resolved with variables on success. |
| `success_speech_llm_prompt` | No | When set, LLM generates success speech (falls back to `success_speech`). |
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

Scheduled workflows do not call the autonomous `workflow` meta-tool. Disabling
or Web-blocking that meta-tool—or setting `"allow_workflow_tool": false` on the
recipe—therefore does not cancel or suppress scheduled tasks. At execution
time, the scheduled runner independently validates every component against its
own mode/profile registry. The scheduled task's stored `timeout_seconds` wraps
the complete worker run even though interactive `PipelineExecutor` execution
has no global wall-clock timeout.

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
.venv/bin/python -m pytest tests/test_workflow_tool_runtime.py tests/test_workflow_availability.py tests/test_web_workflow_availability.py
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
| `bookmark_search.json` | `*` | Search the local Firefox bookmark export. |
| `crypto_market_report.json` | `/crypto` | Crypto prices with Canvas report. |
| `daily_status.json` | `/status` | Weather, crypto, stocks, alerts, and system health dashboard. |
| `daily_status_visual.json` | `/status_visual` | Daily status with generated dashboard image. |
| `deep_dive.json` | `/deep_dive` | Screenshot and analyze a URL with resilient crawl fallback. |
| `deep_research.json` | `/research` | Multi-source research with validation and Canvas output. |
| `github_ai_radar_daily.json` | `/github_ai_radar` | Refresh one rolling GitHub AI Radar Canvas page with search, YouTube, and Brave context. |
| `jarvis_self_check.json` | `/jarvis_self_check` | Check host health, create alerts on problems, and update one Canvas health page. |
| `memory_scan.json` | `/memory_scan` | Analyze the active memory database and save labeled Stash and Canvas reports. |
| `quick_note.json` | `/note` | Save a note to memory and Canvas. |
| `serpapi_amazon_search.json` | `/serpapi_amazon` (also `/amazon_search`, `/serpapi`) | Search Amazon through SerpApi and save Stash and Canvas reports. |
| `server_health_check.json` | `/health` | SSH health check for a remote server. |
| `url_ingest.json` | `/url_ingest` | Crawl a URL, create an Intelligence file, and ingest it for RAG queries. |
| `weather_watch.json` | `/weather_watch` | Default-location weather watch with Canvas and alerts. |
| `web_archive.json` | `/archive` | Fetch a URL, stash content, and create a Canvas summary. |
| `youtube_ingest.json` | `/youtube_ingest` | Download video/transcript and create a briefing. |
| `youtube_research.json` | `/youtube_research` | Transcript-based YouTube study notes. |
| `yt_dlp_release_watch.json` | `/yt_dlp_release_watch` | Detect new stable yt-dlp releases, create a Canvas release report, and raise one deduplicated alert. |

## Authoring Checklist

- Use valid JSON only; no comments.
- Prefer explicit slash triggers.
- Put private local recipes in `data/workflows/personal/*.json`.
- Set `"allow_workflow_tool": false` when a recipe must remain explicit, API-only, or scheduled-only.
- Keep shared workflows portable by reading user-specific defaults from env.
- Use deterministic tool steps before adding `llm_prompt`.
- Validate LLM-generated Canvas content.
- Use `append` for additive logs and `update` for intentional full-page replacement.
- For scheduled workflows, make repeated runs idempotent: update one durable page, append a bounded log, or create clearly dated artifacts.
- For alertable workflows, wire normal `create_alert` steps instead of adding special scheduler-only alert plumbing.
- Run the focused validation commands above before committing.
