# Extended Thinking for Jarvis

**Status**: Implemented and opt-in via `--debug-thinking` or `JARVIS_DEBUG_THINKING`

Jarvis can request provider reasoning or thinking when the selected model supports it. Providers expose this differently: Anthropic can return summarized or explicit thinking blocks, Ollama may return a structured `thinking` field, while OpenAI and xAI generally perform reasoning internally and expose usage or effort controls rather than raw reasoning text.

The feature is off by default, including in the Web UI. The Web UI's ordinary “thinking” status indicator means that a request is in progress; it is not provider reasoning text.

## Quick start

```bash
# Enable for this CLI process and display returned thinking text, when available
./orchestrator/orchestrator_v2.py cloud "Should I save the Bitcoin price?" --debug-thinking

# Enable requests for an entire process/session
export JARVIS_DEBUG_THINKING=true
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Focused regression tests
~/jarvis-venv/bin/python -m pytest tests/test_thinking_adaptive.py
```

`--debug-thinking` sets `JARVIS_DEBUG_THINKING=1` only in the CLI process. Returned thinking is printed in a colored block and logged under `logs/thinking/`.

## Provider behavior

| Provider | What Jarvis does when enabled | What can be displayed |
|---|---|---|
| Anthropic | Reads audited thinking capabilities from `lib/model_catalog.py` and sends adaptive or enabled thinking parameters | Thinking block or adaptive summary returned by Claude |
| OpenAI | Uses the model's normal reasoning behavior; `OPENAI_REASONING_EFFORT` is handled by the OpenAI provider | Raw chain-of-thought is not expected; a separate field is shown only if the API supplies one |
| xAI | Uses `XAI_REASONING_EFFORT` independently of this debug flag | Jarvis records reasoning-token usage but does not normally receive reasoning text |
| Ollama | Sends the native `think` boolean | Structured `message.thinking` when the selected Ollama model returns it |

A model may reason internally without exposing that reasoning. Absence of a displayed thinking block does not mean the model performed no reasoning.

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

If Anthropic thinking is skipped, verify that the exact selected model resolves in `lib/model_catalog.py`. For Ollama, verify that the selected local or cloud model accepts the native `think` option and returns a thinking field.

## Related historical material

Older implementation notes live under `docs/archive/thinking/`. The sequential-thinking MCP design is a separate feature described in `docs/archive/SEQUENTIAL_THINKING_ARCHITECTURE.md`.

**Last updated:** 2026-07-01
