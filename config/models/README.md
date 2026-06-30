# Model Prompt Override Configs

This folder holds small model/provider-specific prompt overlays.

This helps to fine tune model behavior without changing the global prompt.

Different models have there own bad habits or lean toward certain behaviors that can be corrected with a small override.

Use:

```text
config/models/<provider>/<model>/prompt_overrides.yaml
```

Examples:
- `config/models/openai/gpt-5.4-nano/prompt_overrides.yaml`
- `config/models/ollama/qwen3/prompt_overrides.yaml`
- `config/models/ollama/minimax-m3/prompt_overrides.yaml` (matches runtime `minimax-m3:cloud`; suppresses spoken meta lead-ins during TTS condensation)
- `config/models/xai/grok-4.20-reasoning/prompt_overrides.yaml`

Ollama Cloud model IDs use a `:cloud` tag (for example `minimax-m3:cloud`). Prefer a **base folder name without the tag** (`minimax-m3/`, not `minimax-m3:cloud/`) — especially on Windows, where `:` is invalid in paths. Jarvis tries the exact runtime ID first, then falls back to the stripped alias automatically.

Notes:
- The extension is `.yaml` (not `.yml`) in this project.
- Jarvis checks the exact model folder first.
- If no exact file exists, it can fall back to deterministic aliases for:
  - dated model names like `gpt-5.4-nano-2026-03-17`
  - runtime suffixes like `:latest` and `:cloud`
- Missing files are skipped silently.
- Invalid YAML logs a warning and is ignored.
- Supported sections include routing, QA, tool-calling, Completion Guard evaluation, and Intelligence Layer reflection prompt overlays.

Use the template file here as a starting point:

- `config/models/prompt_overrides.example.yaml`
