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
- `config/models/xai/grok-4-fast-reasoning/prompt_overrides.yaml`

Notes:
- The extension is `.yaml` (not `.yml`) in this project.
- Jarvis checks the exact model folder first.
- If no exact file exists, it can fall back to deterministic aliases for:
  - dated model names like `gpt-5.4-nano-2026-03-17`
  - runtime suffixes like `:latest` and `:cloud`
- Missing files are skipped silently.
- Invalid YAML logs a warning and is ignored.

Use the template file here as a starting point:

- `config/models/prompt_overrides.example.yaml`
