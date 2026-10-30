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
| Anthropic | Reads audited capabilities and sends adaptive, manual enabled, disabled, or between-tools thinking with a matching output budget | Thinking summaries only when trace display is enabled |
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
- whether `adaptive`, manual `enabled`, `disabled`, or `between_tools` is supported;
- valid effort levels; and
- aliases such as `fable-5` and `sonnet-5`.

This includes Claude Fable 5. New Anthropic models become eligible after their audited capabilities are added to the catalog; unknown names safely skip optional thinking instead of receiving guessed parameters.

With **Auto** and trace display off, Jarvis uses each model's supported minimum:

| Model | Request behavior | Default output budget |
|---|---|---:|
| Opus 5.5 and Fable 5 | Low adaptive thinking; thinking cannot be disabled | 16,384 tokens |
| Sonnet 5.5 | `between_tools` with low effort; no up-front thinking | 4,096 tokens |
| Other curated models | Explicit `thinking: {type: "disabled"}` | 1,024 tokens |

An explicit effort selects adaptive thinking with a 16,384-token budget on adaptive models, independently of trace visibility. Hidden traces use `display: "omitted"`; visible traces use `display: "summarized"`. Sonnet 5.5's `between_tools` mode takes no display or manual-budget fields. Its explicit effort choices, including `xhigh` and `max`, use adaptive mode instead. Older manual-thinking models retain their 2,000-token thinking budget and 8,000-token output cap when enabled.

When trace display is enabled with Auto, adaptive models use the strongest effort level supported by their catalog entry. Override it when needed:

```bash
ANTHROPIC_EFFORT=low ./orchestrator/orchestrator_v2.py cloud "Compare these options" --debug-thinking
```

An effort unsupported by the selected model is ignored with a warning and replaced by that model's strongest supported value.

`max_tokens` includes thinking as well as answer text. A 1,024-token cap with thinking implicitly enabled can end before any answer appears. Both simple chat and tool chat use the same model-aware configuration; an explicit simple-chat token limit remains authoritative. See Anthropic's [Opus 5.5 migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide) and [Sonnet 5.5 migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide).

For legacy manual-thinking models, simple chat reduces the manual budget when needed to stay below an explicit output cap. A cap of 1,024 tokens or less cannot accommodate Anthropic's minimum manual-thinking budget, so that call uses the model's supported disabled mode.

## Anthropic completion diagnostics

Routing logs retain `anthropic_stop_reason`, `anthropic_max_tokens`, and `anthropic_content_blocks_by_type`. When supplied by Anthropic, thinking-token usage is recorded as `reasoning_tokens` even with trace display off. These diagnostic fields do not include thinking text or signatures, and diagnostic-only results do not invent token accounting.

An exhausted `max_tokens` response is a provider error, including when it contains partial text or tool input. An unfinished `pause_turn` is reported as incomplete, and an empty completion as an empty-response error. No client tool is executed from those responses, and the adapter does not automatically retry or resume them. This preserves usage while avoiding a false successful answer or execution of truncated arguments.

A `refusal` stop reports “Anthropic declined the request.” Its distinct refusal category does not activate tool fallbacks reserved for safety or permission errors, and any client tool input in that response is withheld.

## Thinking logs

Logs are written as JSONL to `logs/thinking/YYYY-MM-DD_decisions.jsonl` only when Jarvis receives thinking text.

```bash
cat logs/thinking/$(date +%Y-%m-%d)_decisions.jsonl | jq '.'
```

These traces are intended for short-lived debugging and routing analysis. They can contain sensitive context, so trace display and storage remain opt-in. Generation may still include billed thinking when a model requires it.

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

**Last updated:** 2026-10-30
