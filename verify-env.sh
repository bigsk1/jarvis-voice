#!/bin/bash
# Quick environment verification script for Jarvis

echo "======================================"
echo "  Jarvis Environment Check"
echo "======================================"
echo ""

# Check Python
echo "🐍 Python:"
python3 --version || echo "  ❌ Python not found"
echo ""

# Check venv
echo "🔧 Virtual Environment:"
if [ -d "$HOME/jarvis-venv" ]; then
  echo "  ✅ Found: ~/jarvis-venv/"
  if [ -f "$HOME/jarvis-venv/bin/activate" ]; then
    echo "  ✅ Activation script exists"
  else
    echo "  ❌ Activation script missing"
  fi
else
  echo "  ❌ Not found: ~/jarvis-venv/"
  echo "     Create with: python3 -m venv ~/jarvis-venv"
fi
echo ""

# Check if venv is active
echo "🌟 Environment Status:"
if [[ "$VIRTUAL_ENV" == *"jarvis-venv"* ]]; then
  echo "  ✅ Virtual environment is ACTIVE"
  echo "     Using: $VIRTUAL_ENV"
else
  echo "  ⚠️  Virtual environment NOT active"
  echo "     Activate with: source ~/jarvis-venv/bin/activate"
fi
echo ""

# Check uv
echo "⚡ Package Manager (uv):"
if command -v uv &> /dev/null; then
  UV_VERSION=$(uv --version)
  echo "  ✅ $UV_VERSION"
  echo "     Fast package installation available!"
else
  echo "  ⚠️  uv not found (will use pip)"
  echo "     Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi
echo ""

# Check Python packages (only if venv is active)
if [[ "$VIRTUAL_ENV" == *"jarvis-venv"* ]]; then
  echo "📦 Required Packages:"
  
  if python -c "import openwakeword" 2>/dev/null; then
    echo "  ✅ openwakeword"
  else
    echo "  ❌ openwakeword - install with: uv pip install openwakeword"
  fi
  
  if python -c "import sounddevice" 2>/dev/null; then
    echo "  ✅ sounddevice"
  else
    echo "  ❌ sounddevice - install with: uv pip install sounddevice"
  fi
  
  if python -c "import numpy" 2>/dev/null; then
    echo "  ✅ numpy"
  else
    echo "  ❌ numpy - install with: uv pip install numpy"
  fi
  
  if python -c "import faster_whisper" 2>/dev/null; then
    echo "  ✅ faster-whisper (for local mode)"
  else
    echo "  ⚠️  faster-whisper (optional, for local mode)"
    echo "     Install with: uv pip install faster-whisper"
  fi
else
  echo "📦 Required Packages:"
  echo "  ⚠️  Activate venv first to check packages"
fi
echo ""

# Check system dependencies
echo "🔨 System Dependencies:"
for cmd in sox ffmpeg aplay jq curl git; do
  if command -v $cmd &> /dev/null; then
    echo "  ✅ $cmd"
  else
    echo "  ❌ $cmd - install with: sudo apt install $cmd"
  fi
done
echo ""

echo "======================================"
if [[ "$VIRTUAL_ENV" == *"jarvis-venv"* ]]; then
  echo "✅ Environment ready! Run: ./jarvis"
else
  echo "⚠️  Activate venv first:"
  echo "   source ~/jarvis-venv/bin/activate"
fi
echo "======================================"

