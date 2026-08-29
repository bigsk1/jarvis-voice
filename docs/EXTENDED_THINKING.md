# Extended Thinking for Jarvis

**Status**: Implemented. Trace display is opt-in via `--debug-thinking` or `JARVIS_DEBUG_THINKING`; generation effort can be selected independently.

Jarvis can request provider reasoning or thinking when the selected model supports it. Providers expose this differently: Anthropic can return summarized or explicit thinking blocks, Ollama may return a structured `thinking` field, while OpenAI and xAI generally perform reasoning internally and expose usage or effort controls rather than raw reasoning text.

Trace display is off by default, including in the Web UI. The Web UI's ordinary
“thinking” status indicator means that a request is in progress; it is not
provider reasoning text.

## Quick start

```bash
# Enable for this CLI process and display returned thinking text, when available
./orchestrator/orchestrator_v2.py cloud "Should I save the Bitcoin price?" --debug-thinking

# Enable requests for an entire process/session
export JARVIS_DEBUG_THINKING=true
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Focused regression tests
.venv/bin/python -m pytest tests/test_thinking_policy.py tests/test_thinking_adaptive.py
```

`--debug-thinking` installs an authoritative process-local override after mode
configuration loads, so `cloud.env` or `local.env` cannot silently turn the CLI
flag back off. Returned thinking is printed in a colored block and logged under
`logs/thinking/`.

To select reasoning depth without displaying the trace, set
`JARVIS_THINKING_EFFORT` or use the per-mode Web UI **Thinking Effort** control.
The value is only sent when the selected model has a validated `thinking`
profile from model YAML or audited catalog metadata. `off` maps to a real
disable when supported, or to the model's declared safe minimum when reasoning
is required. In Web Settings, the control is hidden for unprofiled models and
its choices are rebuilt and validated whenever the provider or model changes.

## Provider behavior

| Provider | What Jarvis does when enabled | What can be displayed |
|---|---|---|
| Anthropic | Reads audited thinking capabilities from `lib/model_catalog.py` and sends adaptive or enabled thinking parameters | Thinking block or adaptive summary returned by Claude |
| OpenAI | Reads audited GPT-5 effort values from `lib/model_catalog.py`; an explicit `JARVIS_THINKING_EFFORT` wins over legacy `OPENAI_REASONING_EFFORT`, while `auto` allows that legacy fallback or otherwise preserves the provider default | Raw chain-of-thought is not expected; a separate field is shown only if the API supplies one |
| xAI | Uses audited per-model effort values for `JARVIS_THINKING_EFFORT`; `XAI_REASONING_EFFORT` remains the provider-specific fallback | Jarvis records reasoning-token usage but does not normally receive reasoning text |
| Ollama | Sends the native `think` boolean for unprofiled models, or a validated effort level for profiled models | Structured `message.thinking` only when trace display is enabled |

A model may reason internally without exposing that reasoning. Absence of a displayed thinking block does not mean the model performed no reasoning.

For OpenAI, the catalog is deliberately model-specific. GPT-5.6 includes
`max`; GPT-5.5, GPT-5.4, and GPT-5.2 top out at `xhigh`; GPT-5.1 tops out at
`high`; and the original GPT-5 Mini/Nano family uses `minimal` rather than
`none`. GPT-4.1, GPT-4o Mini, ChatGPT-aligned aliases, and Codex variants whose
current model pages do not publish an exact effort set remain unprofiled. A
model YAML thinking profile overrides this catalog metadata when one is needed
for a verified model-specific exception.

For xAI, omitting `reasoning_effort` means “use the provider default,” not
“disable reasoning.” Jarvis therefore exposes no **Off** choice for models such
as Grok 4.6 that do not accept a real disabled value; logical off resolves to
their safest audited level. Models such as Grok 4.3 that accept `none` expose
that exact value. Catalog defaults are preserved rather than inferred from the
last value in the supported-level list, and `auto` continues to omit the
parameter so xAI can apply that default.

GLM-5.3 and GLM-5.3-Flash on Ollama Cloud are profiled as required-thinking
models with `low`, `high`, and `max`. Their logical-off behavior is `low`, which
keeps the trace in the provider's separate thinking field; Jarvis discards it
by default. The same resolution is used by simple chat, native tool chat, and
the structured-tool fallback.

## Anthropic source of truth

Anthropic model support is not hardcoded in `lib/thinking.py`. `lib/model_catalog.py` owns:

- whether thinking is supported;
- whether `adaptive` and/or manual `enabled` thinking is supported;
- valid effort levels; and
- aliases such as `fable-5` and `sonnet-5`.

This includes Claude Fable 5. New Anthropic models become eligible after their audited capabilities are added to the catalog; unknown names safely skip optional thinking instead of receiving guessed parameters.

Adaptive models default to the strongest effort level supported by their catalog entry. Override it when needed:

```bash
ANTHROPIC_EFFORT=low ./orchestrator/orchestrator_v2.py cloud "Compare these options" --debug-thinking
```

An effort unsupported by the selected model is ignored with a warning and replaced by that model's strongest supported value.

## Thinking logs

Logs are written as JSONL to `logs/thinking/YYYY-MM-DD_decisions.jsonl` only when Jarvis receives thinking text.

```bash
cat logs/thinking/$(date +%Y-%m-%d)_decisions.jsonl | jq '.'
```

These traces are intended for short-lived debugging and routing analysis. They can contain sensitive context and can increase provider cost, so thinking remains opt-in.

## Troubleshooting

```bash
env | grep JARVIS_DEBUG_THINKING
JARVIS_DEBUG=1 ./orchestrator/orchestrator_v2.py cloud "test" --debug-thinking
```

If Anthropic or xAI thinking is skipped, verify that the exact selected model
has audited capabilities in `lib/model_catalog.py`. For Ollama, verify that the
selected local or cloud model accepts the native `think` option and returns a
thinking field. In JSON mode, Jarvis may recover a parseable JSON object from a
thinking-only response, but it never promotes raw reasoning prose into normal
assistant content.

## Related historical material

Older implementation notes live under `docs/archive/thinking/`. The sequential-thinking MCP design is a separate feature described in `docs/archive/SEQUENTIAL_THINKING_ARCHITECTURE.md`.

**Last updated:** 2026-08-29
