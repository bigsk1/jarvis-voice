#!/bin/bash
# Create systemd-compatible environment file for OpenCode service
# Systemd EnvironmentFile needs KEY=VALUE format (no quotes, no comments)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLOUD_ENV="$PROJECT_ROOT/config/cloud.env"
OPencode_CONFIG_DIR="$HOME/.config/opencode"
SYSTEMD_ENV="$OPencode_CONFIG_DIR/jarvis-env.env"

echo "🔧 Creating systemd environment file for OpenCode..."

# Extract API key variables and remove quotes for systemd format
# Systemd EnvironmentFile supports KEY="VALUE" or KEY=VALUE format
{
    grep -E '^ANTHROPIC_API_KEY=' "$CLOUD_ENV" | head -1
    grep -E '^OPENAI_API_KEY=' "$CLOUD_ENV" | head -1
    echo "OPENCODE_BASE_URL=http://localhost:4096"
} > "$SYSTEMD_ENV"

echo "✅ Created: $SYSTEMD_ENV"
echo ""
echo "📝 Environment variables:"
cat "$SYSTEMD_ENV" | sed 's/=.*/=***/' 
echo ""
echo "💡 This file is used by systemd service: EnvironmentFile=$SYSTEMD_ENV"
echo ""
echo "⚠️  After updating, restart the service:"
echo "   sudo systemctl restart opencode-jarvis.service"

