#!/bin/bash
# Create systemd-compatible environment file for OpenCode service
# Systemd EnvironmentFile needs KEY=VALUE format (no quotes, no comments)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_ENV="${1:-${OPENCODE_ENV_FILE:-$PROJECT_ROOT/config/cloud.env}}"
OPencode_CONFIG_DIR="$HOME/.config/opencode"
SYSTEMD_ENV="$OPencode_CONFIG_DIR/jarvis-env.env"

echo "🔧 Creating systemd environment file for OpenCode..."

if [ ! -f "$SOURCE_ENV" ]; then
    echo "❌ Source env file not found: $SOURCE_ENV"
    exit 1
fi

emit_env_var() {
    local key="$1"
    grep -E "^${key}=" "$SOURCE_ENV" | head -1 || true
}

# Extract OpenCode runtime variables for systemd.
# Systemd EnvironmentFile supports KEY="VALUE" or KEY=VALUE format.
{
    emit_env_var "ANTHROPIC_API_KEY"
    emit_env_var "OPENAI_API_KEY"
    emit_env_var "XAI_API_KEY"
    emit_env_var "OPENCODE_SERVER_USERNAME"
    emit_env_var "OPENCODE_SERVER_PASSWORD"
    echo "OPENCODE_BASE_URL=http://localhost:4096"
} > "$SYSTEMD_ENV"

echo "✅ Created: $SYSTEMD_ENV"
echo ""
echo "📄 Source: $SOURCE_ENV"
echo ""
echo "📝 Environment variables:"
cat "$SYSTEMD_ENV" | sed 's/=.*/=***/' 
echo ""
echo "💡 This file is used by systemd service: EnvironmentFile=$SYSTEMD_ENV"
echo ""
echo "⚠️  After updating, restart the service:"
echo "   sudo systemctl restart opencode-jarvis.service"
