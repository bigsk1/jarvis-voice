# Agent Guidelines for Jarvis Voice Assistant

## Testing & Running
```bash
# Single tool test
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py local "What time is it?"

# Run comprehensive tests
./test-all-tools.sh        # Cloud mode (OpenAI/Anthropic)
./test-all-tools-local.sh  # Local mode (Ollama)

# Voice mode
./jarvis        # Cloud mode
./jarvis-local  # Local mode
```

## Code Style

**Imports**: Standard library first, then third-party, then local modules with `sys.path.insert(0, 'lib')`

**Types**: Use type hints (`from typing import Dict, Any, Optional`)

**Error Handling**: Always wrap I/O in try/except; return `{"ok": False, "error": "msg"}` for tools

**Naming**: snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants

**Tool Interface**: Tools read JSON from stdin/argv, write `{"ok": bool, "speech": str, "data": dict}` to stdout

**Config Loading**: Use `from config_loader import load_config; load_config(mode)` at startup

**Formatting**: 4 spaces, max 100 chars/line, docstrings for functions

**Executables**: Mark scripts executable: `chmod +x script.py`; use shebang `#!/usr/bin/env python3` or `#!/bin/bash`
