#!/bin/bash
# Seed OpenCode 2 config without overwriting an operator's existing settings.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/opencode-setup.py" config "${1:-}"
