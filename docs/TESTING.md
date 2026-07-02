# Jarvis Testing Guide

Jarvis testing is deterministic by default. The normal suite must not rotate a user's databases, rewrite environment files, call paid LLM APIs, or execute state-changing tools.

## Quick start

```bash
cd ~/jarvis-voice

# Safe core smoke group
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_docs_integrity.py \
  tests/test_mode_plumbing_scripts.py
```

The project uses the external `~/jarvis-venv` environment. Override its location with `JARVIS_VENV`; do not create a repository `.venv` merely to run tests.

## Choosing the right level

| Level | Use | Side effects |
|---|---|---|
| Focused pytest | Normal development and regressions | Temporary files/databases and mocks only |
| Multiple focused pytest groups | Before a commit or release | Same deterministic boundary; fresh process per application group |
| Read-only health check | Confirm a configured local service is reachable | Network request to that service |
| Explicit live integration | Validate a real provider/model/service path | May incur cost, create logs, conversations, or service sessions |
| Manual UI/voice test | Validate browser, audio, wake-word, Docker, or tmux behavior | Normal application state |

## Focused regression examples

```bash
# Provider/model behavior
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_model_catalog.py \
  tests/test_llm_provider_anthropic_blocks.py \
  tests/test_ollama_provider_usage.py

# Tool calling and Tool RAG
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_tool_rag_signals.py \
  tests/test_tool_rag_typo_hints.py \
  tests/test_openai_tool_schema.py

# Memory and intelligence
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_memory_db_update_sync.py \
  tests/test_intelligence_maintenance.py \
  tests/test_intelligence_provenance.py

# Web UI/server behavior
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_chat_followup_memory.py \
  tests/test_vision_provider.py
```

Use `rg --files tests | rg '<topic>'` to find the closest regression module rather than reaching for a broad historical shell harness.

An unqualified one-process `pytest` collection is not yet the canonical release command. Several subapplications still expose generic top-level Python packages (`server`, `services`), which can collide in `sys.modules` when Web, Memory, Intelligence, and Canvas tests are collected together. Run focused application/topic groups in separate pytest processes; each group remains deterministic.

## Maintained integration entry points

### Provider thinking

```bash
# No provider calls
./tests/integration/test-thinking-mode.sh

# Two real requests for the selected mode; provider cost/logging applies
./tests/integration/test-thinking-mode.sh --live cloud
```

The script detects the configured provider/model. Anthropic can return displayable thinking summaries; OpenAI and xAI generally reason internally without exposing raw reasoning text; Ollama output is model-dependent.

### OpenCode

```bash
# Mocked client/tool coverage only
./tests/integration/test-opencode-integration.sh

# Read-only configured server/auth check
./tests/integration/test-opencode-integration.sh --health cloud

# One real plan-mode request; creates an OpenCode session and may incur cost
./tests/integration/test-opencode-integration.sh --live cloud
```

The live prompt explicitly tells OpenCode not to create or modify files. It still creates a service session, so it remains opt-in.

## Tool RAG diagnostics

Tool retrieval quality is inspected separately from executing the selected tool:

```bash
./bin/debug-tool-rag.py cloud "What is the current Bitcoin price?"
~/jarvis-venv/bin/python tests/test_tool_similarity.py --mode cloud
./bin/check-embeddings-health.py --both --json
```

After intentionally changing tool schemas or embedding models, refresh the applicable mode explicitly:

```bash
./bin/sync-tools.py cloud
./bin/sync-tools.py local

# Re-embed every definition only when the embedding model/config changed
./bin/sync-tools.py cloud --force
```

Tests must not reset a database merely to obtain a clean Tool RAG index.

## Live manual checks

Some behavior is more honestly verified through the real surface:

- Web UI attachment rendering, media playback, and browser permissions;
- Docker startup and mounted data/config behavior;
- wake-word, microphone, speaker, and TTS paths;
- tmux shutdown and service lifecycle;
- provider safeguards, model retirement fallbacks, and external MCP availability.

Record the mode, provider/model, command or UI action, and relevant log file when reporting a live failure.

## Test authoring contract

1. Prefer pytest and a focused regression reproducer.
2. Use temporary databases and paths; never back up/delete/restore active DBs.
3. Use `config_scope(mode, overrides)` instead of editing env files.
4. Mock provider/service responses unless the test is explicitly live.
5. Make live costs and persistent side effects obvious in `--help` output.
6. Use argument arrays in shell scripts; do not construct executable command strings.
7. Run `bash -n`, ShellCheck, `git diff --check`, and the relevant pytest modules before committing.

See [tests/README.md](../tests/README.md) for the current command index.
