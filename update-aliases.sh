#!/bin/bash
# Script to set up .bashrc aliases for Jarvis Voice Assistant
# For fresh installs or updating existing aliases

set -e

echo "======================================"
echo "  Jarvis Aliases Setup"
echo "======================================"
echo ""

BASHRC="$HOME/.bashrc"
JARVIS_ROOT="$HOME/jarvis-voice"

# Check if .bashrc exists
if [ ! -f "$BASHRC" ]; then
    echo "Creating ~/.bashrc..."
    touch "$BASHRC"
fi

echo "Checking for existing Jarvis aliases..."
echo ""
if grep -q "alias jarvis" "$BASHRC" 2>/dev/null; then
    echo "Found existing aliases:"
    grep -n "alias jarvis" "$BASHRC" || true
    echo ""
    read -p "Replace existing aliases? (y/n): " replace
    if [[ "$replace" != "y" && "$replace" != "Y" ]]; then
        echo "Aborted. No changes made."
        exit 0
    fi
    
    # Create backup
    BACKUP="$HOME/.bashrc.backup-$(date +%Y%m%d-%H%M%S)"
    cp "$BASHRC" "$BACKUP"
    echo "Backup created: $BACKUP"
    
    # Remove old jarvis aliases
    sed -i '/^alias jarvis/d' "$BASHRC"
    sed -i '/^alias say/d' "$BASHRC"
    sed -i '/^alias question/d' "$BASHRC"
    sed -i '/^# Jarvis Voice Assistant/d' "$BASHRC"
    sed -i '/^# Cloud mode/d' "$BASHRC"
    sed -i '/^# Local mode/d' "$BASHRC"
    sed -i '/^# Quick shortcuts/d' "$BASHRC"
    sed -i '/^# Tools/d' "$BASHRC"
    # Clean up any "# OLD:" commented lines from previous runs
    sed -i '/^# OLD: alias jarvis/d' "$BASHRC"
    sed -i '/^# OLD: alias say/d' "$BASHRC"
    sed -i '/^# OLD: alias question/d' "$BASHRC"
fi

echo ""
echo "Adding Jarvis aliases..."

# Add new aliases
cat >> "$BASHRC" << 'EOF'

# ============================================================================
# Jarvis Voice Assistant
# ============================================================================

# Cloud mode (uses cloud APIs: Anthropic, xAI, OpenAI, etc.)
alias jarvis="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis.py"
alias say="$HOME/jarvis-voice/bin/say.sh"
alias question="$HOME/jarvis-voice/bin/question.sh"
alias question-mic="$HOME/jarvis-voice/bin/question-mic.sh"

# Local mode (uses Ollama for LLM, local Whisper for STT)
alias jarvis-local="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis_local.py"
alias say-local="$HOME/jarvis-voice/bin/say-local.sh"
alias question-local="$HOME/jarvis-voice/bin/question-local.sh"
alias question-mic-local="$HOME/jarvis-voice/bin/question-mic-local.sh"

# Tools
alias jarvis-d="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/jarvis-dashboard"
alias jarvis-web="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/start web"
alias jarvis-api="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/start api"

# Quick shortcuts
alias jarvis-cd="cd $HOME/jarvis-voice"
alias jarvis-env="source $HOME/jarvis-venv/bin/activate"
alias jarvis-logs="tail -f $HOME/jarvis-voice/logs/*.log"
EOF

echo ""
echo "✅ Aliases added to ~/.bashrc"
echo ""
echo "Reload with:"
echo "  source ~/.bashrc"
echo ""
echo "Available commands:"
echo "  jarvis          - Start wake word listener (cloud mode)"
echo "  jarvis-local    - Start wake word listener (local mode)"
echo "  jarvis-d        - Open TUI dashboard"
echo "  jarvis-web      - Start web UI"
echo "  jarvis-api      - Start API server"
echo "  say             - Text-to-speech"
echo "  question        - Ask a question (text input)"
echo "  question-mic    - Ask a question (voice input)"
echo "  jarvis-cd       - cd to jarvis-voice directory"
echo "  jarvis-env      - Activate Python venv"
echo "  jarvis-logs     - Tail log files"
echo ""
