---
name: workflow-builder
description: Build, modify, and validate Jarvis workflow JSON definitions. Use when creating or updating data/workflows/*.json or data/workflows/personal/*.json pipelines, adding scheduled-task workflows, wiring Canvas/search/MCP steps, fixing workflow execution failures, or checking that workflow JSON will load reliably.
---

# Jarvis Workflow Builder

Use this repo-tracked skill when a future agent needs to create or repair a Jarvis workflow without rediscovering the workflow system from scratch.

## First Checks

1. Inspect `orchestrator/workflow_loader.py` before assuming discovery behavior. Current workflow files are loaded only from `data/workflows/*.json` and `data/workflows/personal/*.json`.
2. Inspect `data/workflows/README.md` for the authoring contract and `data/workflows/AGENTS.md` for tool outputs and extraction rules.
3. Pick the target path:
   - Shared workflow: `data/workflows/<id>.json`
   - Private local workflow: `data/workflows/personal/<id>.json`
4. Reuse nearby workflows before inventing schema patterns.

## Build Procedure

1. Define a stable `id`, `name`, `description`, `enabled: true`, and explicit slash triggers.
2. Add variables only when steps actually need extracted or defaulted values.
3. Prefer deterministic tool steps over workflow-internal LLM calls when a value can be derived from prior tool output.
4. For workflow-internal LLM steps, add `llm_output_validation` with `min_length`, `reject_patterns`, and `required_patterns` when structure matters.
   - Structured `${...}` values are capped at 3,000 characters by default. Set per-step `llm_variable_max_chars` only when a bounded collection must be passed intact.
5. For workflows that must not use provider-native search inside workflow-internal LLM calls, set `disable_server_side_tools: true`. This does not disable explicit workflow search/MCP steps.
6. Use `mcp_*` tools directly when the workflow needs MCP. FastAPI, scheduled tasks, and CLI execution use the shared MCP-aware registry.
7. For Canvas:
   - Create once with `action: create` and a `not_exists` condition when a durable page is missing.
   - Use `action: append` for additive logs.
   - Use `action: update` only for full-page replacement.
   - If an intentional update may shrink content, set `allow_content_shrink: true` and require full-page headings with `required_patterns`.
   - In Canvas prompts, require raw Markdown only and reject HTML wrappers, code fences, placeholders, and truncated URLs.
8. For alertable workflows, prefer tools that return `alert_title`, `alert_description`, `alert_severity`, and `alert_dedupe_key`, then wire those fields into a normal `create_alert` workflow step. Default alert severity is `high`; explicitly set `low` or `medium` only when the alert should not speak immediately.
9. Keep scheduled-task workflows idempotent: repeated runs should update a durable target, append a bounded log, or create clearly dated artifacts.

## Validation

Run focused checks before handing off:

```bash
.venv/bin/python -m json.tool data/workflows/<id>.json >/dev/null
.venv/bin/python data/workflows/skill/skill.py validate data/workflows/<id>.json
.venv/bin/python data/workflows/skill/skill.py check-loader-scope
```

If Python code changed, run the smallest relevant pytest set. For workflow loader or API discovery changes, include:

```bash
.venv/bin/python -m pytest tests/test_workflow_loader.py tests/test_api_mode_scopes.py tests/test_pipeline_executor.py -q
```

## Helper Script

Use `data/workflows/skill/skill.py` for deterministic checks:

- `validate <workflow.json>` checks common workflow shape mistakes.
- `template --id <id> --trigger /cmd` prints a minimal workflow JSON starter.
- `check-loader-scope` proves this `skill/` folder is ignored by workflow discovery.

## Related Docs

- [data/workflows/AGENTS.md](../AGENTS.md)
- [data/workflows/README.md](../README.md)
