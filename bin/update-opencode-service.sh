#!/bin/bash
# Refresh config/env/plugins and activate the OpenCode 2 service definition.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$SCRIPT_DIR/opencode-setup.py"
python3 "$SETUP" version
python3 "$SETUP" prepare "${1:-}"
RENDERED_FILE="$(mktemp)"
trap 'rm -f "$RENDERED_FILE"' EXIT
python3 "$SETUP" render "$RENDERED_FILE"
sudo install -m 644 "$RENDERED_FILE" /etc/systemd/system/opencode-jarvis.service
sudo systemctl daemon-reload
sudo systemctl restart opencode-jarvis.service
python3 "$SETUP" health
echo "OpenCode V2 service updated and verified."
