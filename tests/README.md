# Jarvis Tests

Jarvis primarily uses deterministic pytest coverage. Tests should use temporary databases, mocked provider responses, and request-local configuration rather than backing up, deleting, or restoring a user's active databases.

## Python environment

Use the external Jarvis environment. The repository intentionally does not use a project-level `.venv`.

Run focused modules in a fresh pytest process:

```bash
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_docs_integrity.py \
  tests/test_mode_plumbing_scripts.py
```

Set `JARVIS_VENV` when the environment lives somewhere else.

Do not currently use an unqualified `pytest` command as the release signal. Jarvis Web, Memory, Intelligence, and Canvas still contain generic top-level package names such as `server` and `services`; collecting every application test in one Python process can resolve a later test against an earlier application's imported package. Run the relevant application/topic group in a fresh process until those package namespaces are consolidated.

## Focused checks

```bash
# Model catalogs and provider audits
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_model_catalog.py \
  tests/test_anthropic_model_audit.py \
  tests/test_xai_model_audit.py \
  tests/test_openai_model_audit.py

# Memory and mode isolation
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_memory_db_update_sync.py \
  tests/test_memory_sync_health.py \
  tests/test_mode_plumbing_scripts.py

# Tool RAG
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_tool_rag_signals.py \
  tests/test_tool_rag_typo_hints.py

# Intelligence
~/jarvis-venv/bin/python -m pytest -q \
  tests/test_intelligence_maintenance.py \
  tests/test_intelligence_provenance.py \
  tests/test_intelligence_redaction.py \
  tests/test_intelligence_server_side_tools.py
```

## Maintained integration scripts

Only two shell integration entry points remain. Their default behavior is deterministic and does not call paid provider APIs.

| Script | Default | Explicit external checks |
|---|---|---|
| `tests/integration/test-thinking-mode.sh` | Catalog and mocked provider tests | `--live cloud`, `--live local`, or `--live all` |
| `tests/integration/test-opencode-integration.sh` | Mocked OpenCode client/tool tests | `--health cloud\|local` or `--live cloud\|local` |

Examples:

```bash
./tests/integration/test-thinking-mode.sh
./tests/integration/test-opencode-integration.sh

# Read-only OpenCode server check using cloud.env URL/auth
./tests/integration/test-opencode-integration.sh --health cloud

# Explicit paid/stateful checks
./tests/integration/test-thinking-mode.sh --live cloud
./tests/integration/test-opencode-integration.sh --live cloud
```

OpenCode `--live` creates a session. Thinking `--live` makes real LLM requests and writes normal conversation/thinking logs. Neither option is run implicitly.

## Manual diagnostics

These are diagnostics rather than pass/fail integration suites:

```bash
# Inspect Tool RAG retrieval for one query without asking the routing LLM to execute it
./bin/debug-tool-rag.py cloud "What is the current Bitcoin price?"

# Inspect similarity rankings against the current tool index
~/jarvis-venv/bin/python tests/test_tool_similarity.py --mode cloud

# Check mode-specific embedding/index health
./bin/check-embeddings-health.py --both --json
```

Diagnostics can read or initialize mode-specific databases and may call the configured embedding provider. They do not delete and restore active databases.

## Safety rules for new tests

- Put deterministic regression coverage in pytest.
- Use `tmp_path`, temporary SQLite files, mocks, and `config_scope()` overrides.
- Never rewrite `config/cloud.env` or `config/local.env` to select a test model.
- Never delete, rename, back up, or restore active databases from a test.
- Gate paid APIs, external services, workspace writes, and persistent sessions behind an explicit `--live` or similarly clear flag.
- Invoke Python through `${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python`.
- State external side effects and costs in the script's usage text.
