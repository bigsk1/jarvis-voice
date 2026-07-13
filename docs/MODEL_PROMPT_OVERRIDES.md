# Model Prompt Overrides

> Purpose: Add small, surgical prompt overlays for specific provider/model combinations so Jarvis can correct stable model quirks without changing the global prompt behavior for the whole app.

## Why This Exists

Different models often have different behavioral quirks even when the rest of Jarvis stays the same.

Examples:
- one model prefers direct product links, another returns only ASINs
- one model follows strict JSON formatting well, another needs a stronger reminder
- one model over-explains, another under-specifies tool-facing intent
- local Ollama models can vary significantly in routing, verbosity, and instruction-following

The existing global prompts are designed for broad correctness. They are not a good place to patch one model-specific habit if doing so would worsen behavior for other providers.

Model prompt overrides solve that by letting Jarvis load **small, targeted prompt text** only when the effective provider/model matches exactly.

## Core Principles

1. **Small and surgical**
   - These are quirk patches, not alternate personalities
   - Keep them short and specific

2. **Exact first, normalized alias second**
   - Jarvis checks the exact provider/model path first
   - If that file does not exist, Jarvis can fall back to a deterministic normalized alias for common runtime suffixes like dated releases, `:latest` / `:cloud`, and bare runtime suffixes such as `-latest` / `-cloud`
   - No fuzzy matching, no “closest model” inference

3. **Graceful failure**
   - Bad YAML should log a warning and be ignored
   - Missing keys should not break startup or requests

4. **Stage-specific injection**
   - Different prompt stages have different needs
   - A shopping/QA nudge should not automatically affect Completion Guard or feedback

5. **Do not silently fork the app**
   - Global system behavior still lives in the main prompts
   - Overrides should be easy to find, review, and disable

## File Layout

```text
config/
  models/
    openai/
      gpt-5.4-nano/
        prompt_overrides.yaml
    xai/
      grok-4.20-non-reasoning/
        prompt_overrides.yaml
    ollama/
      qwen3/
        prompt_overrides.yaml
```

One file per provider/model pair or normalized alias.

This keeps behavior modular and makes it easy to compare model-specific tuning over time.

Scaffolding included in the repo:
- `config/models/prompt_overrides.example.yaml`
- provider roots:
  - `config/models/openai/`
  - `config/models/anthropic/`
  - `config/models/xai/`
  - `config/models/ollama/`

Use the `.yaml` extension consistently in this project.

## YAML Format

```yaml
enabled: true
description: "OpenAI GPT-5.4 Nano behavior tuning"
applies_to_modes: [cloud, local]

routing_prepend: |
  Prefer direct, concrete product links over bare identifiers when the user asks for products, listings, or things to buy.

routing_append: |
  Preserve exact product names and model numbers.

qa_prepend: |
  When recommending products, prefer 2-4 concrete options with short reasoning.

qa_append: |
  If a direct link is available, prefer it over only giving an identifier.

tool_calling_prepend: |
  Make the primary action explicit before supporting context.

completion_guard_eval_prepend: |
  Judge the answer based on whether it delivered the requested outcome, not just whether it sounded plausible.
```

## Supported Fields

### Metadata

- `enabled`
  - `true` or `false`
  - If omitted, treat as enabled

- `description`
  - Free-form note for humans
  - Optional

- `applies_to_modes`
  - Optional array of `cloud` and/or `local`
  - If omitted, applies to both

### Prompt Sections

- `routing_prepend`
- `routing_append`
- `qa_prepend`
- `qa_append`
- `tool_calling_prepend`
- `completion_guard_eval_prepend`
- `intelligence_reflection_prepend`

Future sections can be added later if they prove necessary, but the initial version should stay small.

## Match Rules

Jarvis should load an override **only** if:
- provider matches exactly
- model matches exactly OR resolves to a supported normalized alias
- mode is allowed by `applies_to_modes` if present
- YAML parsed successfully
- `enabled` is not `false`

Examples:
- `openai / gpt-5.4-nano` → load only `config/models/openai/gpt-5.4-nano/prompt_overrides.yaml`
- `openai / gpt-5.4-nano-2026-03-17` → first try `config/models/openai/gpt-5.4-nano-2026-03-17/prompt_overrides.yaml`, then fall back to `config/models/openai/gpt-5.4-nano/prompt_overrides.yaml`
- `ollama / qwen3:latest` → first try `config/models/ollama/qwen3:latest/prompt_overrides.yaml`, then fall back to `config/models/ollama/qwen3/prompt_overrides.yaml`
- `ollama / kimi-k2.5:cloud` → first try `config/models/ollama/kimi-k2.5:cloud/prompt_overrides.yaml`, then fall back to `config/models/ollama/kimi-k2.5/prompt_overrides.yaml`
- `xai / grok-4.20-non-reasoning-latest` → first try `config/models/xai/grok-4.20-non-reasoning-latest/prompt_overrides.yaml`, then fall back to `config/models/xai/grok-4.20-non-reasoning/prompt_overrides.yaml`
- `xai / grok-4.20-non-reasoning-cloud` → first try `config/models/xai/grok-4.20-non-reasoning-cloud/prompt_overrides.yaml`, then fall back to `config/models/xai/grok-4.20-non-reasoning/prompt_overrides.yaml`
- `openai / gpt-5.4` → do **not** load the `gpt-5.4-nano` override

This is intentionally strict. Normalization is limited to deterministic runtime suffix cleanup, not fuzzy matching.

## Failure Handling

### Missing file

No warning needed. Treat as normal:
- no override
- continue normally

### Invalid YAML

Log a warning and skip the override:
- startup/request should continue
- no prompt injection should occur from that file

Example warning:
- `[MODEL_PROMPTS] Invalid YAML for openai/gpt-5.4-nano: ...`

### Unknown keys

Ignore unknown keys with a warning or debug note.

This allows safe future expansion without breaking older code.

### Missing section keys

Safe to skip.

Example:
- file contains only `routing_prepend`
- other sections are simply treated as empty

Blank strings are fine, but not required.

## Injection Points

The main idea is to inject into the prompt stage that actually needs tuning.

### 1. Routing prompt

Best place for:
- tool-use emphasis
- query shaping
- “make the main intent explicit”
- shopping/research nuance

Likely hook:
- `orchestrator/router_v2.py`
- around `self._system_prompt_base` / `system_prompt`

### 2. QA / synthesis prompts

Best place for:
- answer structure
- link preference vs identifiers
- result presentation style

Likely hook:
- `orchestrator/orchestrator_v2.py`
- the explicit synthesis / condense prompts, not necessarily every casual voice rewrite

### 3. Tool-calling prompt stage

Best place for:
- nudges that affect how the model chooses between tools or frames a tool task

This may overlap with routing, so the first version should keep this conservative.

### 4. Completion Guard evaluator

Best place for:
- judge-model-specific quirks
- stricter completion criteria
- repair scoring nuance

Likely hook:
- `jarvis-web/server/sockets/chat.py`
- only inside Completion Guard evaluation prompts

## Precedence and Conflicts

### General Rule

The main prompt remains the source of truth.

Overrides are a **higher-priority model-specific patch layer**, but only within the section where they are injected.

### Practical meaning

- `prepend` sections should appear **before** the main section text they are modifying
- `append` sections should appear **after**
- if the override conflicts with the main prompt, the model will see both, but the closer/higher-priority injected text should bias behavior for that model

### Design guidance

Avoid writing direct contradictions if possible.

Good:
- “When listing buyable products, prefer direct links over bare identifiers.”

Bad:
- main prompt says “be concise”
- override says “be extremely detailed and verbose in all cases”

The cleaner pattern is:
- keep main prompt broad
- use overrides to narrow one model’s behavior for one stage

## Token and Cost Impact

Yes, overrides add to token usage automatically because they become part of the prompt.

That is why they must stay small.

Expected impact:
- a few short paragraphs per active section is usually fine
- giant override files would become hidden context bloat

Design recommendation:
- keep each section under a few hundred characters when possible
- avoid examples unless the example is truly necessary
- do not duplicate large chunks of the main prompt

## Logging and Visibility

When an override is loaded, Jarvis should log it clearly.

Example:
- `[MODEL_PROMPTS] Loaded override for openai/gpt-5.4-nano (sections: routing_prepend, qa_append)`

If nothing matches:
- no warning
- no behavior change

If YAML is invalid:
- warning
- skip

This is important for debugging “why did this model behave differently?” later.

## Interaction With Feedback and Intelligence

- **Main chat / routing / QA / tool-calling overrides** apply to their respective runtime prompts.
- **`intelligence_reflection_prepend`** is injected into intelligence reflection prompts when configured.
- **Feedback and other analysis flows** do not inherit model-specific runtime patches unless given their own future override sections.

Possible future sections, if ever needed:
- `feedback_prepend`
- `reflection_prepend`

But these should be added only after a concrete repeated need appears.

## Implemented Scope

### Scope

Start with:
- `routing_prepend`
- `routing_append`
- `qa_prepend`
- `qa_append`
- `tool_calling_prepend`
- `completion_guard_eval_prepend`
- `intelligence_reflection_prepend`

Skip more exotic sections until the basic pattern proves useful.

### Loader behavior

1. Determine effective provider/model
2. Try exact path:
   - `config/models/<provider>/<model>/prompt_overrides.yaml`
3. If exact path is missing, try deterministic aliases:
   - strip `:latest` / `:cloud`
   - strip bare `-latest` / `-cloud`
   - strip dated suffixes like `-2026-03-17`
4. If file missing → return empty override
5. If invalid YAML → warning + empty override
6. If `enabled: false` → skip
7. If `applies_to_modes` excludes current mode → skip
8. Return only recognized string sections

### Runtime behavior

At each supported prompt stage:
- inject `prepend` before main prompt block
- inject `append` after main prompt block
- do nothing if section missing

## Example Use Cases

### Shopping behavior

One model:
- returns direct links and concrete product options

Another model:
- returns only ASINs or generic search phrases

Fix:
- add a small `qa_prepend` asking for direct buyable listings when available

### Local-model JSON behavior

One local model:
- often adds extra prose around structured output

Fix:
- add a small `routing_prepend` or `completion_guard_eval_prepend` reinforcing exact output shape

### Overly vague product/entity handling

One model:
- gets distracted by topical nouns in the product title

Fix:
- add a `routing_prepend` telling it to preserve exact model numbers and prioritize the user’s requested action over background topic words

## Non-Goals

This system should **not** become:
- a full second prompt framework
- per-user personalization
- hidden behavior overrides for everything
- a replacement for fixing bad global prompts
- a replacement for better tool descriptions or better Tool RAG

It is a **targeted compatibility layer**.

## Recommendation

This is a good architectural fit for Jarvis:
- modular
- provider/model aware
- low blast radius
- useful for both frontier cloud models and quirky local Ollama models

If implemented conservatively, it gives you a clean way to tune specific model behavior without destabilizing the rest of the app.
