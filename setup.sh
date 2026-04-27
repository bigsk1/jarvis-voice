#!/bin/bash
# Jarvis Voice Assistant - Setup/Migration Script
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "======================================"
echo "  Jarvis Voice Assistant - Setup"
echo "======================================"
echo ""

# Check dependencies
echo "🔍 Checking dependencies..."
MISSING_DEPS=()

for cmd in sox ffmpeg aplay jq curl git python3 traceroute; do
  if ! command -v $cmd &> /dev/null; then
    MISSING_DEPS+=("$cmd")
  fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
  echo "❌ Missing dependencies: ${MISSING_DEPS[*]}"
  echo "   Install with: sudo apt install sox ffmpeg alsa-utils jq curl git python3 traceroute inetutils-traceroute"
  exit 1
fi
echo "✅ All system dependencies found"

# Check Python packages
# Currently jarvis-venv is one level up from project root and been using for this project, if starting new need to adjust alaises and apths to use a new venv in this project.
echo ""
echo "🐍 Checking Python packages..."
if ! python3 -c "import openwakeword" 2>/dev/null; then
  echo "⚠️  openwakeword not found"
  echo "   Install with: pip install openwakeword"
fi

if ! python3 -c "import sounddevice" 2>/dev/null; then
  echo "⚠️  sounddevice not found"
  echo "   Install with: pip install sounddevice"
fi

if ! python3 -c "import faster_whisper" 2>/dev/null; then
  echo "⚠️  faster-whisper not found (only needed for local mode)"
  echo "   Install with: pip install faster-whisper"
fi

# Check config files
echo ""
echo "📝 Checking configuration..."

if [ ! -f "config/cloud.env" ]; then
  echo "⚠️  Cloud config not found. Copy from example:"
  echo "   cp config/cloud.env.example config/cloud.env"
  echo "   chmod 600 config/cloud.env"
fi

if [ ! -f "config/local.env" ]; then
  echo "⚠️  Local config not found. Copy from example:"
  echo "   cp config/local.env.example config/local.env"
  echo "   chmod 600 config/local.env"
fi

# Secure permissions on config files (git doesn't preserve these)
echo ""
echo "🔐 Securing config file permissions..."
chmod 600 config/*.env config/*.json 2>/dev/null || true
echo "✅ Config files secured (600)"

# Create audio directories
echo ""
echo "📁 Creating audio directories..."
mkdir -p audio/cloud/{recordings,tts,mic,logs}
mkdir -p audio/local/{recordings,tts,mic,logs}
echo "✅ Audio directories created"

# Create convenience aliases/symlinks
echo ""
echo "🔗 Creating convenience symlinks..."
ln -sf "$PROJECT_ROOT/bin/wake-jarvis.py" "$PROJECT_ROOT/jarvis" 2>/dev/null || true
ln -sf "$PROJECT_ROOT/bin/wake-jarvis-local.py" "$PROJECT_ROOT/jarvis-local" 2>/dev/null || true
echo "✅ Symlinks created (./jarvis and ./jarvis-local)"

# Git check (repo should already be cloned)
echo ""
if [ -d ".git" ]; then
  echo "✅ Git repository detected"
else
  echo "⚠️  No .git directory found. Did you clone the repo?"
  echo "   git clone https://github.com/bigsk1/jarvis-voice.git"
fi

echo ""
echo "======================================"
echo "  Setup Complete! ✅"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Configure audio devices in config/cloud.env:"
echo "   • SPEAKER_DEVICE_NAME - run: aplay -L | grep -E '^(plughw|hw):'"
echo "   • MIC_DEVICE_NAME - run: arecord -L | grep -E '^(plughw|hw):'"
echo ""
echo "2. Add your API keys to config/cloud.env:"
echo "   • XAI_API_KEY or ANTHROPIC_API_KEY (LLM)"
echo "   • ELEVENLABS_API_KEY or OPENAI_API_KEY (TTS)"
echo ""
echo "3. Run verification:"
echo "   ./verify-env.sh"
echo ""
echo "4. Sync tools to database:"
echo "   ./setup_tools.sh"
echo ""
echo "5. Start Jarvis:"
echo "   ./bin/start        # Start all services"
echo "   ./jarvis           # Start wake word listener"
echo ""
echo "See docs/INSTALL_GUIDE.md for full setup guide."
echo ""

