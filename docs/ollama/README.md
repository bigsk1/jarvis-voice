# Ollama Cloud Mode: Integration Game Plan

Status: Planning (April 2026)

## The Problem

The codebase treats `LLM_PROVIDER=ollama` as a proxy for `mode=local`.
This is baked into ~25 files across daemons, services, the web UI, and config
loading.  The Ollama API is identical for local and cloud-tagged models (the
`:cloud` suffix is just an Ollama registry convention), so the `OllamaProvider`
class already works for both.  The coupling is purely in the plumbing around it.

Today, Ollama cloud works only through Completion Guard eval overrides (the
path we just fixed).  Setting `LLM_PROVIDER=ollama` in `cloud.env` with a
`:cloud` model would break mode detection, daemon behavior, UI provider
dropdowns, and context-window defaults.

## Current State

### What works

| Use case | Status | Notes |
|---|---|---|
| Ollama as primary LLM in local mode | Works | The default path |
| Ollama `:cloud` as Completion Guard eval | Works | Via UI override or env `JARVIS_COMPLETION_GUARD_EVAL_PROVIDER=ollama` |
| `OLLAMA_BASE_URL` pointing to remote server | Works | Already set in `cloud.env` to `192.168.70.226:11434` |
| `fetch_ollama_models()` filtering by `:cloud` tag | Works | `settings_manager.py:64-78` already splits local vs cloud |

### What doesn't work

Setting `LLM_PROVIDER=ollama` in cloud mode triggers a chain of incorrect
assumptions:

1. **`config_loader.py:58`** — `load_config()` auto-detection: `ollama` -> loads `local.env`
2. **~12 daemons/services** — derive `mode = 'local'` from `provider == 'ollama'`
3. **`settings_manager.py:366`** — locks eval provider dropdown to `['ollama']` in local mode
4. **`settings_manager.py:552`** — rejects non-ollama providers when mode is local
5. **`router_v2.py:628`** — uses `retrieval_limit = 5` (local) instead of 15 (cloud)
6. **`_get_context_options()`** — hardcoded model-family list, no `:cloud` awareness
7. **All `create_provider("ollama", ...)` callsites** — read `OLLAMA_MODEL` which defaults to local models

### The ollama == local assumption (full inventory)

**Hard gates (actively block cloud use):**

```
config_loader.py:58            load_config() auto-detect: ollama -> local.env
settings_manager.py:366        eval_provider options: ['ollama'] in local mode only
settings_manager.py:552        rejects non-ollama eval providers in local mode
scheduled_task_runner.py:26    mode = 'local' if provider == 'ollama'
scheduled_task_runner.py:31,41 sets LLM_PROVIDER='ollama' for local tasks
```

**Mode derivation (ollama -> local):**

```
reminder_scheduler.py:223      mode = 'local' if provider == 'ollama'
follow_up_daemon.py:194        mode = 'local' if provider == 'ollama'
self_healing_daemon.py:547     mode = 'local' if provider == 'ollama'
alert_manager.py:38            mode = 'local' if provider == 'ollama'
api/server.py:422              mode = 'local' if LLM_PROVIDER == 'ollama'
api/routes/voice.py:135        mode = 'local' if LLM_PROVIDER == 'ollama'
api/routes/query.py:66         sets LLM_PROVIDER = 'ollama' for local
api/routes/workflows.py:272    sets LLM_PROVIDER = 'ollama' for local
intelligence.py:2004           mode = 'local' if provider == 'ollama'
prompt_versioning.py:99        mode = 'local' if LLM_PROVIDER == 'ollama'
prompt_evolution.py:89         mode = 'local' if LLM_PROVIDER == 'ollama'
memory_db.py:33                checks provider == 'ollama' for local db path
```

**Soft defaults (wrong but not fatal):**

```
router_v2.py:565               default provider: 'ollama' only when mode == 'local'
router_v2.py:628               retrieval_limit = 5 for local (should be 15 for cloud ollama)
llm_provider.py:894-905        _get_context_options(): hardcoded model family list
llm_provider.py:770-889        chat(): num_predict multiplier only for :cloud tag
feedback.py:330                OLLAMA_BASE_URL default localhost
stash.py:153-154               OLLAMA_BASE_URL default localhost
```

## Proposed Solution: `resolve_mode()` Helper

Instead of scattering `provider == 'ollama' -> local` logic across 25 files,
introduce a single function that all code uses to determine mode.

### New: `lib/config_loader.py`

```python
def resolve_mode(provider: str | None = None) -> str:
    """Determine operating mode from explicit config, not provider name.

    Priority:
      1. JARVIS_MODE env var (explicit override)
      2. Which .env file was loaded (cloud.env vs local.env)
      3. Legacy fallback: ollama -> local (backward compat)
    """
    explicit = os.environ.get('JARVIS_MODE', '').strip().lower()
    if explicit in ('cloud', 'local'):
        return explicit

    # If load_config() was already called, it sets _JARVIS_LOADED_MODE
    loaded = os.environ.get('_JARVIS_LOADED_MODE', '').strip().lower()
    if loaded in ('cloud', 'local'):
        return loaded

    # Legacy fallback
    prov = (provider or os.environ.get('LLM_PROVIDER', '')).strip().lower()
    if prov == 'ollama' and ':cloud' not in os.environ.get('OLLAMA_MODEL', '').lower():
        return 'local'

    return 'cloud'
```

Update `load_config()` to stamp `_JARVIS_LOADED_MODE`:

```python
def load_config(mode=None):
    if mode is None:
        mode = resolve_mode()
    os.environ['_JARVIS_LOADED_MODE'] = mode
    # ... rest unchanged
```

### New env var: `JARVIS_MODE`

Add to `cloud.env` / `local.env`:

```bash
# cloud.env
JARVIS_MODE=cloud

# local.env
JARVIS_MODE=local
```

This is the explicit override that makes everything unambiguous.  Existing
setups without it fall back to the current behavior via `resolve_mode()`.

### New env vars: `OLLAMA_CLOUD_MODEL`

```bash
# cloud.env
OLLAMA_CLOUD_MODEL=minimax-m2.5:cloud    # used when provider=ollama in cloud mode
OLLAMA_MODEL=qwen3                        # still used for local mode
```

Provider creation reads the right one:

```python
# router_v2.py, feedback.py, etc.
elif provider_type == "ollama":
    if resolve_mode() == 'cloud':
        model = get_config_value("OLLAMA_CLOUD_MODEL",
                get_config_value("OLLAMA_MODEL", "qwen3"))
    else:
        model = get_config_value("OLLAMA_MODEL", "qwen3")
```

## Migration Plan

### Phase 1: Foundation (low risk, no behavior change)

Add `resolve_mode()` to `config_loader.py` and `JARVIS_MODE` to both env files.
With no `JARVIS_MODE` set, `resolve_mode()` returns exactly what the old
`provider == 'ollama'` checks returned.  No files change behavior.

**Files touched:**
- `lib/config_loader.py` (add `resolve_mode()`, update `load_config()`)
- `config/cloud.env`, `config/local.env` (add `JARVIS_MODE`)
- `config/cloud.env.example`, `config/local.env.example` (document it)

**Test:** Run cloud and local modes, verify nothing changes.

### Phase 2: Replace mode derivation (~15 files)

Replace every `mode = 'local' if provider == 'ollama' else 'cloud'` with
`mode = resolve_mode()`.  This is a mechanical find-and-replace.  Behavior
stays identical because `resolve_mode()` preserves the legacy fallback.

**Files touched (one-line change each):**

```
services/reminder_scheduler.py
services/follow_up_daemon.py
services/self_healing_daemon.py
services/scheduled_task_runner.py
api/managers/alert_manager.py
api/managers/scheduled_task_manager.py
api/server.py
api/routes/voice.py
lib/intelligence.py
lib/prompt_versioning.py
lib/prompt_evolution.py
lib/memory_db.py
```

**Pattern:**
```python
# Before
mode = 'local' if get_config_value('LLM_PROVIDER', 'anthropic') == 'ollama' else 'cloud'

# After
from config_loader import resolve_mode
mode = resolve_mode()
```

**Test:** Run cloud and local modes again, verify identical behavior.

### Phase 3: Settings UI and provider dropdown

Allow `ollama` in the cloud-mode provider dropdown and remove the hard gate
that rejects non-ollama providers in local mode.

**Files touched:**
- `settings_manager.py:366` — always include `ollama` in eval provider options
- `settings_manager.py:552` — remove the local-only ollama enforcement
- `settings_manager.py:419-431` — always fetch ollama models if ollama is configured
- `jarvis-web/server/routes/api.py` — update default fallback logic

### Phase 4: Provider creation and model selection

Add `OLLAMA_CLOUD_MODEL` support so cloud mode picks `:cloud` tagged models
by default.

**Files touched:**
- `router_v2.py:588-594` — read `OLLAMA_CLOUD_MODEL` when `resolve_mode() == 'cloud'`
- `feedback.py:330-346` — same pattern
- `intelligence.py:1000-1003` — same pattern
- `pipeline_executor.py:129-131` — same pattern
- `stash.py:153-154` — same pattern
- `lib/self_play.py:639-643` — same pattern
- `lib/tool_builder.py:676-680` — same pattern

### Phase 5: Context, limits, and options tuning

Local Ollama models run on constrained hardware (GPU VRAM, local CPU).  The
`options` dict sent with every Ollama API request (`num_ctx`, `num_predict`,
`temperature`) exists to work within those constraints.  Cloud models don't
have these limits — the remote backend manages context windows, token budgets,
and sampling, just like any other cloud provider.

Sending local-tuned options to cloud models is wasteful at best and can
cause problems (e.g. `num_ctx=48000` forces a context size the cloud
backend may interpret differently, or `num_predict=300` starves a model
that counts thinking tokens against that budget — the exact bug we just
fixed).

**Current local-only options being sent to all Ollama models:**

| Option | Where set | Local purpose | Cloud impact |
|---|---|---|---|
| `num_ctx` | `_get_context_options()` | Limit context to fit GPU VRAM (48K in local.env) | Unnecessary — cloud manages this |
| `num_predict` | `chat()`, `stash.py`, `status_llm.py` | Cap output tokens for speed on local GPU | Harmful — cloud models count thinking against this |
| `temperature` | `chat()` (json_mode=0), `stash.py`, `status_llm.py` | Deterministic output from weaker models | Fine for cloud too, but defaults differ |

**Fix: `_get_context_options()` should skip local tuning for cloud models:**

```python
def _get_context_options(self) -> dict[str, Any]:
    options = {}
    if ':cloud' in self.model.lower():
        # Cloud backends manage their own context and sampling.
        # Don't impose local GPU constraints.
        return options

    model_lower = self.model.lower()
    if any(m in model_lower for m in ['qwen3', 'ministral', 'mistral-nemo', 'llama3']):
        from config_loader import get_int
        context_window = get_int('OLLAMA_CONTEXT_WINDOW', 32000)
        options["num_ctx"] = context_window
    return options
```

**Other callsites that need the same guard:**

- `stash.py:164-167` — `num_predict` and `temperature` in Ollama branch
- `status_llm.py:215-219` — same pattern
- `chat():849-854` — already has `is_cloud` multiplier, could skip `num_predict`
  entirely for cloud and let the backend decide

**Files touched:**
- `llm_provider.py:894-905` — early return for `:cloud` models
- `llm_provider.py:849-854` — skip `num_predict` for cloud, or keep the 4x multiplier
  as-is (already working)
- `router_v2.py:628` — use `resolve_mode()` for retrieval limit (cloud ollama
  should get 15 tools, not 5)
- `stash.py`, `status_llm.py` — guard local-only options behind `:cloud` check

## Local vs Cloud: What Changes

The Ollama API is identical.  What differs is **how we configure the request**:

| Concern | Local (GPU) | Cloud (`:cloud` tag) |
|---|---|---|
| `num_ctx` | Required — fits model to GPU VRAM (e.g. 32K) | Skip — backend manages context |
| `num_predict` | Set explicitly for speed/VRAM | Skip or set high — thinking tokens count against it |
| `temperature` | Tune per-model (smaller models need lower temp) | Standard defaults like any cloud provider |
| `format` (structured JSON schema) | Works — local Ollama enforces grammar | Use `"json"` only — cloud backends may not support schema |
| `think: false` | Honored by local models | Ignored by cloud backends — model still thinks internally |
| `OLLAMA_CONTEXT_WINDOW` | Critical — prevents OOM on GPU | Irrelevant |
| `OLLAMA_MODEL` | Local model name (e.g. `qwen3.5:latest`) | N/A for cloud |
| `OLLAMA_CLOUD_MODEL` | N/A for local | Cloud model name (e.g. `minimax-m2.5:cloud`) |
| Tool retrieval limit | 5 (small context) | 15 (same as other cloud providers) |
| `OLLAMA_BASE_URL` | Usually `localhost:11434` | Remote server (e.g. `192.168.70.226:11434`) |

The `:cloud` suffix on the model name is the simplest detection mechanism.
`_get_context_options()` and other callsites can check
`':cloud' in self.model.lower()` to decide which options to send.

current ollama local settings/options work good already and like to preserve those. Tested and proven.

current cloud modelfiles downloaded on ollama server and ready to use. if using cloud ollama option add to existing token count feature to track costs and context length.

qwen3.5:cloud    
minimax-m2.7:cloud         
glm-5:cloud     
minimax-m2.5:cloud    
qwen3-coder-next:cloud

## Config Reference (Final State)

### cloud.env

```bash
JARVIS_MODE=cloud
LLM_PROVIDER=xai                           # primary: xai, anthropic, openai, ollama
OLLAMA_BASE_URL="http://192.168.70.226:11434"
OLLAMA_CLOUD_MODEL=minimax-m2.5:cloud       # used when LLM_PROVIDER=ollama in cloud mode
OLLAMA_MODEL=qwen3                          # still here for local fallback / reference

# Completion Guard can use ollama independently of primary LLM
JARVIS_COMPLETION_GUARD_EVAL_PROVIDER=ollama
JARVIS_COMPLETION_GUARD_EVAL_MODEL=minimax-m2.5:cloud
```

### local.env

```bash
JARVIS_MODE=local
LLM_PROVIDER=ollama
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_MODEL=qwen3.5:latest                 # local model
# OLLAMA_CLOUD_MODEL not needed in local mode
```

## Risk Assessment

| Phase | Risk | Mitigation |
|---|---|---|
| 1 | None | Pure addition, no behavior change |
| 2 | Low | Mechanical replacement, `resolve_mode()` preserves legacy logic |
| 3 | Medium | UI changes; test both modes in web UI after |
| 4 | Medium | Multiple create_provider callsites; grep to verify all caught |
| 5 | Low | Context/limit tuning, easy to test |

## What NOT to Do

- **Don't create a separate `OllamaCloudProvider` class.** The Ollama API is
  identical for local and cloud models.  The `:cloud` tag is just a model
  registry convention, not a different protocol.

- **Don't add a fifth provider type.**  `create_provider("ollama", ...)` works
  for both.  The distinction is in model selection and mode config, not the
  provider implementation.

- **Don't change the meaning of `mode`.** Cloud and local modes control database
  paths, embedding dimensions, config files, and more.  Mode should stay tied
  to infrastructure, not to which LLM company runs the model.

## Quick Validation Checklist

After each phase, confirm:

```bash
# Cloud mode (primary xai, ollama for CG eval)
./orchestrator/orchestrator_v2.py cloud "What time is it?" --json

# Local mode (primary ollama local)
./orchestrator/orchestrator_v2.py local "What time is it?" --json

# Web UI: settings page loads, provider dropdowns populate
# Web UI: Completion Guard eval fires and parses (check server logs)
```

After Phase 4, also test:

```bash
# Cloud mode with ollama as primary LLM
# (set LLM_PROVIDER=ollama, OLLAMA_CLOUD_MODEL=minimax-m2.5:cloud in cloud.env)
./orchestrator/orchestrator_v2.py cloud "What is 2 plus 2?" --json
```
