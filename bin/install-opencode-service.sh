#!/bin/bash
# Install the independently supervised, confined OpenCode 2 service.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$SCRIPT_DIR/opencode-setup.py"
# Refuse V1 before touching configuration, plugins, credentials, or systemd.
python3 "$SETUP" version
python3 "$SETUP" prepare "${1:-}"
RENDERED_FILE="$(mktemp)"
trap 'rm -f "$RENDERED_FILE"' EXIT
python3 "$SETUP" render "$RENDERED_FILE"
sudo install -m 644 "$RENDERED_FILE" /etc/systemd/system/opencode-jarvis.service
sudo systemctl daemon-reload
sudo systemctl enable opencode-jarvis.service
sudo systemctl restart opencode-jarvis.service
python3 "$SETUP" health
echo "OpenCode V2 service installed; use journalctl -u opencode-jarvis.service for logs."
