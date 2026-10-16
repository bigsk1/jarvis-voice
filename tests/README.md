# Jarvis Tests

Jarvis uses deterministic pytest coverage with temporary data and mocked external
services. The maintained execution and test-authoring rules live in
[the testing guide](../docs/TESTING.md).

## Python environment

Use the repo `.venv` for development (`uv sync --dev --frozen` if needed):

```bash
# Canonical full core suite (Python and core UI Node tests)
./bin/test-suite

# Check sandbox/local HTTP support without running tests
./bin/test-suite --preflight-only

# Focused checks while developing
.venv/bin/python -m pytest -q \
  tests/test_docs_integrity.py \
  tests/test_mode_plumbing_scripts.py
```

The full runner executes the collected suite in one process, isolates operator
configuration, and leaves a unique report folder under ignored `logs/tests/`.
Use `--report-dir` to choose another report location. A preflight exit of **3**
means a required local fixture reported an explicit EPERM or EACCES permission
denial before pytest ran. If the sandbox blocked it, rerun the same command
outside the sandbox with the required permission. Exit
**4** is a preflight timeout, not proof of a sandbox denial; investigate the
reported phase before choosing a retry. Pytest failures remain failures. See the
[execution boundaries and reports](../docs/TESTING.md#full-suite-execution-and-sandbox-boundaries).

The Firefox extension's `npm test` in `jarvis-firefox-extension/` is separate.
Report it as unrun when only the core suite ran, and give its result separately
when run. If a shell exports `UV_PROJECT_ENVIRONMENT` for production, prepare
the dev environment with `UV_PROJECT_ENVIRONMENT=.venv uv sync --dev --frozen`.

## Focused checks

```bash
# Model catalogs and provider audits
.venv/bin/python -m pytest -q \
  tests/test_model_catalog.py \
  tests/test_anthropic_model_audit.py \
  tests/test_xai_model_audit.py \
  tests/test_openai_model_audit.py

# Memory and mode isolation
.venv/bin/python -m pytest -q \
  tests/test_memory_db_update_sync.py \
  tests/test_memory_sync_health.py \
  tests/test_mode_plumbing_scripts.py

# Tool RAG
.venv/bin/python -m pytest -q \
  tests/test_tool_rag_signals.py \
  tests/test_tool_rag_typo_hints.py

# Intelligence
.venv/bin/python -m pytest -q \
  tests/test_intelligence_maintenance.py \
  tests/test_intelligence_provenance.py \
  tests/test_intelligence_redaction.py \
  tests/test_intelligence_server_side_tools.py
```

## Maintained integration scripts

The two maintained shell wrappers retain
`${JARVIS_VENV:-$HOME/jarvis-venv}`. Their default behavior is deterministic; real
provider/server checks require the explicit options below.

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

## Writing tests

Follow the [test authoring contract](../docs/TESTING.md#test-authoring-contract):
controlled clocks and explicit configuration, complete fixtures, cleaned-up
state, distinct application imports, and the selected Python for child commands.
Keep real providers and private databases out of deterministic tests. Do not
hide failures with skips or xfails. Run focused regressions first and the full
suite after changes to shared behavior.
