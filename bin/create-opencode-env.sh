#!/bin/bash
# Merge the selected mode's OpenCode credentials into a private systemd env file.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/opencode-setup.py" env "${1:-}"
