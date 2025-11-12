#!/bin/bash
# Install OpenCode systemd service for Jarvis

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_FILE="$PROJECT_ROOT/systemd/opencode-jarvis.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ Service file not found: $SERVICE_FILE"
    exit 1
fi

echo "📦 Installing OpenCode systemd service..."

# Create environment file for systemd
echo "🔧 Creating environment file..."
"$PROJECT_ROOT/bin/create-opencode-env.sh"

# Copy service file
sudo cp "$SERVICE_FILE" /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable opencode-jarvis.service

# Start service
echo "🚀 Starting OpenCode service..."
sudo systemctl start opencode-jarvis.service

# Wait a moment
sleep 2

# Check status
if sudo systemctl is-active --quiet opencode-jarvis.service; then
    echo "✅ OpenCode service is running!"
    echo ""
    echo "📊 Status:"
    sudo systemctl status opencode-jarvis.service --no-pager -l
    echo ""
    echo "📝 Useful commands:"
    echo "   sudo systemctl status opencode-jarvis.service"
    echo "   sudo journalctl -u opencode-jarvis.service -f"
    echo "   sudo systemctl restart opencode-jarvis.service"
else
    echo "❌ Service failed to start. Check logs:"
    echo "   sudo journalctl -u opencode-jarvis.service -n 50"
    exit 1
fi

