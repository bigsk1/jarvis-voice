# Extended Thinking for Jarvis

**Status**: Implemented (opt-in via `--debug-thinking` or `JARVIS_DEBUG_THINKING`)

Extended thinking lets you see provider-side reasoning before Jarvis acts — useful for debugging grey-area decisions (auto-save, tool choice, memory vs search).

---

## Quick start

```bash
# One-off debug run (cloud)
./orchestrator/orchestrator_v2.py cloud "Should I save the Bitcoin price?" --debug-thinking

# Always on for a session
export JARVIS_DEBUG_THINKING=true
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Automated test suite
./tests/integration/test-thinking-mode.sh
```

With thinking enabled on a supported model, console output includes a colored **LLM Thinking** block before the speech response.

---

## How it works

| Component | Role |
|-----------|------|
| `lib/thinking.py` | Model detection, thinking config, extraction, display, log analysis |
| `lib/llm_provider.py` | Anthropic extended thinking; OpenAI o-series; Ollama DeepSeek R1 tags |
| `orchestrator/router_v2.py` | Passes `enable_thinking`; captures 4-tuple `(text, tool_call, usage, thinking)` |
| `orchestrator/orchestrator_v2.py` | `--debug-thinking` flag; formatted console display |
| `logs/thinking/` | Daily JSONL: `YYYY-MM-DD_decisions.jsonl` |

**Trigger**: `--debug-thinking` sets `JARVIS_DEBUG_THINKING=1`, or set `JARVIS_DEBUG_THINKING=true` in `config/cloud.env` / `config/local.env`.

Non-thinking models **gracefully skip** (no error) — e.g. default local `qwen3.5:latest`.

---

## Supported models

### Anthropic (native extended thinking)

- `claude-sonnet-4-5-20250929` (recommended)
- Other Sonnet 4.x family models with thinking API support

### OpenAI (reasoning models)

- `o1`, `o1-preview`, `o1-mini`, `o3-mini` (when configured as `LLM_PROVIDER`)

### Ollama (select models)

- `deepseek-r1` — `<think>` tag extraction (recommended local thinking model)
- `qwq`, some coder variants
- **Not** default `qwen3.5:latest` — skips thinking, runs normally

Check runtime support:

```bash
python3 -c "from lib.thinking import is_thinking_supported; print(is_thinking_supported('anthropic', 'claude-sonnet-4-5-20250929'))"
```

---

## Thinking logs

Logs land in `logs/thinking/YYYY-MM-DD_decisions.jsonl` (one JSON object per line).

```bash
# Tail today's decisions
cat logs/thinking/$(date +%Y-%m-%d)_decisions.jsonl | jq '.'

# Count auto-save vs skip
cat logs/thinking/$(date +%Y-%m-%d)_decisions.jsonl | jq '.decision.saved' | sort | uniq -c
```

Use for tuning memory prompts, tool routing, and grey-area scenarios (excited about a movie, ephemeral prices, etc.).

---

## Manual test scenarios

| Scenario | Command | Expected |
|----------|---------|----------|
| Ephemeral data | `... cloud "What time is it?" --debug-thinking` | Thinking notes don't save |
| Grey area | `... cloud "I'm excited about the new Predator movie" --debug-thinking` | Visible save/skip reasoning |
| Local non-thinking | `... local "What time is it?" --debug-thinking` with `qwen3.5:latest` | No thinking block, normal answer |
| Local thinking | `OLLAMA_MODEL=deepseek-r1` + `--debug-thinking` | Reasoning visible if model emits tags |

---

## Cost (Anthropic)

Roughly **~0.3¢ per complex decision** with thinking enabled (thinking tokens billed as input; system prompt caching reduces effective cost). Recommended for **debugging and tuning**, not necessarily always-on in production.

---

## Troubleshooting

**Thinking not showing?**

```bash
env | grep JARVIS_DEBUG_THINKING
JARVIS_DEBUG=1 ./orchestrator/orchestrator_v2.py cloud "test" --debug-thinking
```

**Logs not created?**

```bash
ls -la logs/thinking/
chmod 755 logs/thinking/
```

**Wrong model?** Confirm `LLM_PROVIDER` / `ANTHROPIC_MODEL` / `OLLAMA_MODEL` supports thinking (see table above).

---

## Future / not implemented

These were explored in planning but are **not** the current implementation:

- **Sequential Thinking MCP** — structured `think_step` tools via MCP (see the [archived architecture proposal](archive/SEQUENTIAL_THINKING_ARCHITECTURE.md) for design notes)
- **Always-on thinking in production** — today opt-in only
- **OpenAI non-o-series** — no thinking unless using o1/o3-family models

---

## Historical docs

Branch milestone write-ups (Nov 2025) live in `archive/thinking/`:

- `archive/thinking/THINKING_MODE_COMPLETE.md`
- `archive/thinking/THINKING_MODE_TESTING.md`
- `archive/thinking/THINKING_IMPLEMENTATION_STATUS.md`

---

**Last updated:** 2026-05-25
