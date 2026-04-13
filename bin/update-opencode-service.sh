#!/bin/bash
# Update OpenCode service with environment variables and restart

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_FILE="$PROJECT_ROOT/systemd/opencode-jarvis.service"
RENDER_SCRIPT="$PROJECT_ROOT/bin/render-systemd-unit.sh"
RENDERED_FILE="$(mktemp)"
trap 'rm -f "$RENDERED_FILE"' EXIT

echo "🔧 Updating OpenCode service environment..."

# Create/update environment file
"$PROJECT_ROOT/bin/create-opencode-env.sh"

# Render and install updated service file
echo "📦 Updating systemd service..."
"$RENDER_SCRIPT" "$SERVICE_FILE" "$RENDERED_FILE"
sudo install -m 644 "$RENDERED_FILE" /etc/systemd/system/opencode-jarvis.service

# Reload systemd
sudo systemctl daemon-reload

# Restart service to pick up new environment variables
echo "🔄 Restarting OpenCode service..."
sudo systemctl restart opencode-jarvis.service

# Wait a moment
sleep 2

# Check status
if sudo systemctl is-active --quiet opencode-jarvis.service; then
    echo "✅ OpenCode service restarted successfully!"
    echo ""
    echo "📊 Verifying environment variables are loaded..."
    # Check if API keys are available (via config endpoint)
    if curl -s http://localhost:4096/config | jq -e '.provider.anthropic.options.apiKey' > /dev/null 2>&1; then
        echo "✅ API keys are configured"
    else
        echo "⚠️  API keys may not be visible via config endpoint (this is normal)"
    fi
    echo ""
    echo "🧪 Test with: ./tests/integration/test-opencode-integration.sh"
else
    echo "❌ Service failed to restart. Check logs:"
    echo "   sudo journalctl -u opencode-jarvis.service -n 50"
    exit 1
fi
