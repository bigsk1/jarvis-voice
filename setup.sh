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

for cmd in sox ffmpeg aplay jq curl git python3; do
  if ! command -v $cmd &> /dev/null; then
    MISSING_DEPS+=("$cmd")
  fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
  echo "❌ Missing dependencies: ${MISSING_DEPS[*]}"
  echo "   Install with: sudo apt install sox ffmpeg alsa-utils jq curl git python3"
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
  echo "⚠️  Cloud config not found. Copying template..."
  cp config/config.env.template config/cloud.env
  echo "   → Please edit config/cloud.env with your OpenAI API key"
fi

if [ ! -f "config/local.env" ]; then
  echo "⚠️  Local config not found. Copying template..."
  cp config/config.env.template config/local.env
  echo "   → Please edit config/local.env with your Ollama/Kokoro endpoints"
fi

# Create audio directories
echo ""
echo "📁 Creating audio directories..."
mkdir -p audio/cloud/{recordings,tts,mic,logs}
mkdir -p audio/local/{recordings,tts,mic,logs}
echo "✅ Audio directories created"

# Create convenience aliases/symlinks
echo ""
echo "🔗 Creating convenience symlinks..."
ln -sf "$PROJECT_ROOT/bin/wake_jarvis.py" "$PROJECT_ROOT/jarvis" 2>/dev/null || true
ln -sf "$PROJECT_ROOT/bin/wake_jarvis_local.py" "$PROJECT_ROOT/jarvis-local" 2>/dev/null || true
echo "✅ Symlinks created (./jarvis and ./jarvis-local)"

# Git setup
echo ""
if [ -d ".git" ]; then
  echo "✅ Git repository already initialized"
else
  echo "🔧 Initializing git repository..."
  git init
  git config user.name "Jarvis Dev"
  git config user.email "jarvis@localhost"
  echo "✅ Git initialized"
fi

# Initial commit
if [ -z "$(git log --oneline 2>/dev/null)" ]; then
  echo ""
  echo "📝 Creating initial commit..."
  git add -A
  git commit -m "Initial commit: Jarvis Voice Assistant structured project

- Organized directory structure
- Centralized configuration (cloud.env, local.env)
- Refactored scripts to use config loader
- Separate audio storage for cloud/local modes
- Git-based version control (local only)
- Ready for future extensions (orchestrator, tools)"
  echo "✅ Initial commit created"
fi

echo ""
echo "======================================"
echo "  Setup Complete! ✅"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Edit config files:"
echo "   • config/cloud.env (Anthropic API key)"
echo "   • config/local.env (Ollama/Kokoro endpoints)"
echo ""
echo "2. Activate your Python virtual environment:"
echo "   source ~/jarvis-venv/bin/activate"
echo ""
echo "3. Run Jarvis:"
echo "   • Cloud mode:  ./jarvis"
echo "   • Local mode:  ./jarvis-local"
echo ""
echo "4. Create feature branches for experiments:"
echo "   git checkout -b feature/my-new-capability"
echo ""
echo "5. Your will need to set your own speaker and mic names in the config files and requirements.txt has full packages needed using uv to install everything is prefered"
echo "   This setup was never designed to be reproducible or used by others so you will need to set your own values and install the packages yourself."
echo ""

