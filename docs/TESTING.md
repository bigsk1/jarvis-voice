# Jarvis Testing Guide

Jarvis testing is deterministic by default. The normal suite must not rotate a user's databases, rewrite environment files, call paid LLM APIs, or execute state-changing tools.

## Quick start

```bash
cd ~/jarvis-voice

# Complete deterministic core suite (Python and core UI Node tests)
./bin/test-suite

# Same complete suite with two worker processes, grouped by test file
./bin/test-suite --workers 2

# Environment check only, without collecting or executing tests
./bin/test-suite --preflight-only

# Focused checks during development
.venv/bin/python -m pytest tests/test_docs_integrity.py tests/test_mode_plumbing_scripts.py -q
```

Use the repository `.venv` for development. If it is missing or lacks the locked
development dependencies, run `uv sync --dev --frozen`; do not upgrade packages
as a test repair. Production launchers, the maintained integration shell scripts,
and Tool RAG sync have separate environment contracts described below.
If a production shell exports `UV_PROJECT_ENVIRONMENT`, select the development
target explicitly: `UV_PROJECT_ENVIRONMENT=.venv uv sync --dev --frozen`.

## Full-suite execution and sandbox boundaries

`./bin/test-suite` runs all collected tests under `tests/` serially by default.
Use `./bin/test-suite --workers 2` for two worker processes with pytest-xdist's
`loadfile` distribution: every test in a file stays on the same worker. Both modes
use one pytest invocation, the same isolation/preflight, and one combined report.
The development lockfile includes pytest-xdist; it is not a production dependency.

Use parallel mode for faster feedback, and retain serial runs before releases
and when investigating shared-state failures. Separate worker processes can hide
cross-file import/global-state contamination that a serial run exposes. Do not
accept parallel success as a workaround for a failing serial run. Tests must use
temporary files/databases and ephemeral ports; worker processes still share the
checkout and host resources. Session fixtures run once per worker, not once for
the whole run. Worker crashes fail the run without automatic worker restarts.

This includes the standalone core UI `*.test.js` suites through
`tests/test_javascript_regressions.py`, alongside Python tests that use Node
fixtures. Node must be available on `PATH`. The separately packaged Firefox
extension retains its own `npm test` command in `jarvis-firefox-extension/`;
run that component's checks when changing the extension. Report the core suite
and extension suite separately, explicitly marking the extension unrun when
only the core command ran.
Run a focused reproducer while developing, then this command after shared
runtime, configuration, fixture, or cross-surface changes. The complete run
checks interactions that individually green modules can miss. The runner accepts
`--report-dir` for an alternate report location; use pytest directly for selected
test paths or other focused pytest arguments.

Before pytest starts, the runner checks local TCP sockets and a bounded
AnyIO/FastAPI `TestClient` exchange. These checks use temporary local resources,
not Jarvis servers or external providers. Some agent sandboxes forbid these
operations even though the tests themselves are deterministic.

- **Exit 3 before pytest:** a local fixture reported an explicit EPERM or EACCES
  permission denial. Inspect the preflight report. If the sandbox blocked it,
  rerun the same complete command outside the sandbox with the required
  permission. Do not modify application code, skip tests, or treat this as a
  provider outage.
- **Exit 4 before pytest:** a preflight phase exceeded its 10-second bound. The
  output names the last startup phase. Investigate a slow dependency import or
  stalled fixture; a timeout alone does not establish a sandbox restriction or
  warrant an automatic outside-sandbox retry. No tests ran.
- **Pytest reports a failure or error:** investigate it as a test or application
  problem. Successful preflight is not permission to dismiss later failures as
  sandbox artifacts. Only a reproduced environment restriction warrants that
  classification.
- **A completed green run:** all collected deterministic tests passed. Explicitly
  gated live-browser or long-encoding checks remain separate; their skipped
  reasons are visible in the report.

Each run uses a unique report folder under ignored `logs/tests/` by default.
Completed pytest runs retain `pytest.log`, JUnit `results.xml`, and `summary.json`
with the command, environment/preflight outcome, result, JUnit case counts, and
individual skip reasons. The summary also records worker count and distribution.
JUnit case counts exclude separately reported passing
subtests; `pytest.log` retains pytest's authoritative terminal totals.
A preflight-only or blocked run does not have pytest results because no tests
executed. Use these
artifacts to compare failures, rather than relying on a truncated terminal view.

The runner removes inherited `PYTEST_ADDOPTS` and `PYTEST_PLUGINS`, and clears
`JARVIS_LIVE_BROWSER_TEST`, `JARVIS_TEST_LONG_ENCODE`, and optional private-media
sample paths (`JARVIS_TEST_VIDEO`, `JARVIS_TEST_IMAGE`), so shell settings cannot
silently select a smaller run or enable live work. It places the chosen Python
environment first on `PATH` for child commands. Inherited pytest worker identity
and automatic worker-count settings are cleared; `--workers` controls execution.
The test isolation in
`tests/conftest.py` intercepts the Python config loader's reads of exactly this
checkout's private `cloud.env` / `local.env`, returning no operator values.
It preserves mode ownership for setting names declared in the public `.example`
files, so a scoped read cannot fall through to an inherited mode-owned setting;
explicit config overrides still work. Child environment exports also discard
unoverridden inherited mode-owned settings only when the selected private-file
read was redacted. Temporary config roots and explicit mode-config fixtures keep
their real values and ownership rules. Recognized inherited application settings are
cleared before collection, and environment and request config scopes are
restored after each test.

This fixture is not a filesystem sandbox. Direct `open()`, shell `source`, and
child processes can still read the operator's real files. Tests exercising those
paths must use copied temporary checkout/config fixtures. Every test must still
declare its settings and mock external boundaries.

Explicit opt-ins still work with targeted direct pytest commands; the full
runner clears them for a reproducible default run. Exporting
`JARVIS_LIVE_BROWSER_TEST=1` does not disable isolation for other collected
tests. Only the live browser branch explicitly reads selected operator settings
through `load_live_mode_config()` and passes them as scoped/deployment overrides,
without hydrating the global environment.

After 90 seconds in one test, faulthandler prints thread stacks for diagnosis;
this diagnostic does not stop the test. The whole run is bounded separately.
Timeouts and cancellation stop pytest's process group, including fixture
children. They produce a nonzero result; use `--timeout SECONDS` to adjust the
default 30-minute bound for a slower development machine.

## Choosing the right level

| Level | Use | Side effects |
|---|---|---|
| Focused pytest | Normal development and regressions | Temporary files/databases and mocks only |
| Full suite (`./bin/test-suite`) | Catch shared-state and cross-component regressions | Temporary local resources, mocked external services |
| Read-only health check | Confirm a configured local service is reachable | Network request to that service |
| Explicit live integration | Validate a real provider/model/service path | May incur cost, create logs, conversations, or service sessions |
| Manual UI/voice test | Validate browser, audio, wake-word, Docker, or tmux behavior | Normal application state |

## Focused regression examples

```bash
# Provider/model behavior
.venv/bin/python -m pytest -q \
  tests/test_model_catalog.py \
  tests/test_llm_provider_anthropic_blocks.py \
  tests/test_ollama_provider_usage.py

# Tool calling and Tool RAG
.venv/bin/python -m pytest -q \
  tests/test_tool_rag_signals.py \
  tests/test_tool_rag_typo_hints.py \
  tests/test_openai_tool_schema.py

# Memory and intelligence
.venv/bin/python -m pytest -q \
  tests/test_memory_db_update_sync.py \
  tests/test_intelligence_maintenance.py \
  tests/test_intelligence_provenance.py

# Web UI/server behavior
.venv/bin/python -m pytest -q \
  tests/test_chat_followup_memory.py \
  tests/test_vision_provider.py
```

Use `rg --files tests | rg '<topic>'` to find the closest regression module rather than reaching for a broad historical shell harness.

Tests importing different subapplications must use distinct package aliases via
`tests/server_package_utils.py`; generic `server` / `services` imports can resolve
to another application's modules in a combined run. Do not make separate
processes the permanent workaround for a missing import boundary.

Canvas tests use `load_canvas_server_package()` from the same helper. It supplies
package-local configuration with temporary page, media, and Stash storage before
Canvas's eager imports. Patch the imported module objects for each test rather
than injecting a global `config` or purging another app's `server` modules. The
native-launcher regression uses a copied temporary checkout in a fresh interpreter
to check the real configuration paths and import graph.

## Maintained integration entry points

These shell wrappers retain their production-style
`${JARVIS_VENV:-$HOME/jarvis-venv}` Python selection. Set `JARVIS_VENV` explicitly
when using another environment. Their opt-in live modes are outside the normal
full-suite command.

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
# Deterministic V2 client/tool/progress coverage through repo .venv when available
./tests/integration/test-opencode-integration.sh

# Read-only configured server/auth check
./tests/integration/test-opencode-integration.sh --health cloud

# One real plan-mode request; creates an OpenCode session and may incur cost
./tests/integration/test-opencode-integration.sh --live cloud
```

The live prompt explicitly tells OpenCode not to create or modify files. It still creates a service session, so it remains opt-in.
Health and live checks use `${JARVIS_VENV:-$HOME/jarvis-venv}` and the selected
mode's server URL/authentication. Health checks require an OpenCode 2.x server;
they do not prove provider/model access or workspace protection.

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

Tool RAG sync intentionally requires the external production environment and
refuses the repository `.venv`. It contacts the configured embedding host; use
the applicable network permission when running inside an agent sandbox. Sync and
health diagnostics are not automatic full-suite prerequisites. Tests must not
reset a database merely to obtain a clean Tool RAG index.

## Live manual checks

Some behavior is more honestly verified through the real surface:

- Web UI attachment rendering, media playback, and browser permissions;
- Docker startup and mounted data/config behavior;
- wake-word, microphone, speaker, and TTS paths;
- tmux shutdown and service lifecycle;
- provider safeguards, model retirement fallbacks, and external MCP availability;
- tool credential availability: `./bin/manage-tools.py --mode cloud list` and
  `tests/test_tool_availability.py`, `tests/test_web_provider_availability.py`.

Record the mode, provider/model, command or UI action, and relevant log file when reporting a live failure.

## Test authoring contract

1. **Reproduce behavior through the relevant caller.** Verify meaningful results,
   side effects, and rejected paths. A mocked tool's response alone does not
   prove the orchestrator returned its receipt. Keep focused tests first, then
   run the full suite after changes that can affect shared behavior.
2. **Own the clock.** Use fixed timezone-aware datetimes for scheduling and date
   parsing, and controlled numeric clocks for heartbeat/TTL tests. Advance the
   test clock explicitly to cover expiry. Do not call `time.time()` or
   `datetime.now()` in collection-time parametrization, or use a calendar date
   whose validity depends on when the suite runs.
3. **Own configuration.** Declare the mode, provider, model, and feature settings
   the test exercises with `config_scope(mode, overrides)` or the appropriate
   patched getter. Do not depend on the operator's active model or optional
   services. The shared fixture blocks loader reads, not direct file access:
   shell and child-process tests need temporary config/checkout fixtures.
   Test catalog delegation with a controlled catalog response; keep
   exact current model/order/default invariants in the authoritative catalog
   tests and update those when intentionally changing the catalog.
4. **Restore state.** Use `monkeypatch`, context-managed patches, and fixture
   teardown for environment, config scopes, registries, caches, `sys.path`,
   module aliases, threads, and processes owned by the test. Shared default
   isolation is a backstop, not a substitute for releasing resources or clearing
   feature-specific singleton caches. Use unique application package aliases.
5. **Use complete, lightweight fixtures.** Prefer real schemas/value objects
   with mocked services. If bypassing a constructor, supply every dependency
   the exercised method actually uses. A copied shell checkout must include its
   invoked helpers and dependencies, with HTTP, encoders, playback, and other
   effects replaced at their real boundaries.
6. **Keep children in the test environment.** Invoke Python children with
   `sys.executable`; provide a controlled `PATH` when exercising launchers that
   call `python3`. Use argument arrays and bounded subprocess timeouts. Shell
   tests must not accidentally find an unrelated system Python or launch a
   production service.
7. **Separate historical benchmarks from generic unit tests.** Frozen replay
   prompts/schema hashes protect report comparability. Test runner lifecycle
   with a coherent synthetic prompt/replay pair, and test mismatched snapshot
   refusal explicitly. Do not rewrite an immutable snapshot or remove a drift
   guard merely to make an unrelated control-flow test pass.
8. **Use temporary data and mocked external services.** Never rewrite private
   mode files or use, delete, rename, back up, or restore active databases to
   make a test pass. A live provider call, tool mutation, persistent session,
   real workspace write, or billable integration requires a clearly explicit
   live entry point describing its costs and side effects.
9. **Keep failures visible.** Do not add skips, xfails, retries, broad exception
   handling, or weaker assertions to hide a real regression. Distinguish
   preflight environment restrictions from actual failures and preserve the
   reports. Intentional platform/live-test gates must remain specific and
   documented.
10. **Validate the changed language and full boundary.** Run relevant pytest and
    Node tests, Ruff/type checks for Python changes, shell syntax/ShellCheck for
    shell changes, and `git diff --check`. Report a full-suite failure honestly;
    focused green tests alone do not establish a green full suite.

See [tests/README.md](../tests/README.md) for the current command index.
