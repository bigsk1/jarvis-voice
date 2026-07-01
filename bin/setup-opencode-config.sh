#!/bin/bash
# Setup OpenCode configuration for Jarvis
# This script creates/updates OpenCode config with Ollama support

set -e

OPencode_CONFIG_DIR="$HOME/.config/opencode"
OPencode_CONFIG="$OPencode_CONFIG_DIR/opencode.json"
# Get project root (parent of bin directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
JARVIS_CONFIG_DIR="$PROJECT_ROOT/config"

echo "🔧 Setting up OpenCode configuration..."

# Create config directory if it doesn't exist
mkdir -p "$OPencode_CONFIG_DIR"

# Check if config already exists
if [ -f "$OPencode_CONFIG" ]; then
    echo "⚠️  OpenCode config already exists at: $OPencode_CONFIG"
    echo "   Backup created: ${OPencode_CONFIG}.backup"
    cp "$OPencode_CONFIG" "${OPencode_CONFIG}.backup"
fi

# Load Jarvis config to get Ollama URL
if [ -f "$JARVIS_CONFIG_DIR/local.env" ]; then
    echo "📖 Loading Ollama URL from: $JARVIS_CONFIG_DIR/local.env"
    source "$JARVIS_CONFIG_DIR/local.env"
    OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
    IFS=',' read -r -a OLLAMA_URL_CANDIDATES <<< "$OLLAMA_URL,http://localhost:11434"
    OLLAMA_URL="$(echo "${OLLAMA_URL_CANDIDATES[0]}" | xargs)"
    OLLAMA_URL="${OLLAMA_URL%/}"
    echo "   Found OLLAMA_BASE_URL candidates: ${OLLAMA_BASE_URL:-http://localhost:11434}"
    echo "   Using primary Ollama URL for OpenCode: $OLLAMA_URL"
else
    echo "⚠️  local.env not found, using default Ollama URL"
    OLLAMA_URL="http://localhost:11434"
fi

# Ensure Ollama URL ends with /v1 for OpenAI-compatible API
if [[ "$OLLAMA_URL" != */v1 ]]; then
    OLLAMA_URL="${OLLAMA_URL%/}/v1"
fi

# Create config with correct OpenCode format
cat > "$OPencode_CONFIG" << EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": {
        "baseURL": "$OLLAMA_URL"
      },
      "models": {
        "mistral-nemo": {
          "name": "Mistral Nemo"
        }
      }
    },
    "openai": {
      "npm": "@ai-sdk/openai",
      "name": "OpenAI",
      "options": {
        "apiKey": "{env:OPENAI_API_KEY}"
      },
      "models": {
        "gpt-4o": {
          "name": "GPT-4o"
        }
      }
    },
    "anthropic": {
      "npm": "@ai-sdk/anthropic",
      "name": "Anthropic",
      "options": {
        "apiKey": "{env:ANTHROPIC_API_KEY}"
      },
      "models": {
        "claude-sonnet-5": {
          "name": "Claude Sonnet 5"
        },
        "claude-sonnet-4-5-20250929": {
          "name": "Claude Sonnet 4.5"
        }
      }
    }
  },
  "disabled_providers": ["cloudflare-workers", "amazon-bedrock", "nvidia", "workers-ai", "bedrock", "huggingface"],
  "autoupdate": true,
  "permission": {
    "edit": "ask",
    "bash": "ask"
  }
}
EOF

echo "✅ OpenCode config created at: $OPencode_CONFIG"
echo "   (This is the global config used by both server and TUI)"
echo ""
echo "📝 Configuration:"
echo "   - Ollama provider: $OLLAMA_URL"
echo "   - Default provider: anthropic (claude-sonnet-5)"
echo ""
echo "💡 To use Ollama in local mode, Jarvis will automatically select it."
echo "   For cloud mode, OpenCode will use Anthropic Claude by default."
