#!/bin/bash
# Script to set up shell aliases for Jarvis Voice Assistant
# Supports bash (.bashrc) and zsh (.zshrc)
# For fresh installs or updating existing aliases

set -e

echo "======================================"
echo "  Jarvis Aliases Setup"
echo "======================================"
echo ""

JARVIS_ROOT="$HOME/jarvis-voice"

# Detect shell and set appropriate rc file
if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ] || [ "$SHELL" = "/usr/bin/zsh" ]; then
    RCFILE="$HOME/.zshrc"
    SHELL_NAME="zsh"
elif [ -n "$BASH_VERSION" ] || [ "$SHELL" = "/bin/bash" ] || [ "$SHELL" = "/usr/bin/bash" ]; then
    RCFILE="$HOME/.bashrc"
    SHELL_NAME="bash"
else
    # Default to bashrc
    RCFILE="$HOME/.bashrc"
    SHELL_NAME="bash"
fi

echo "Detected shell: $SHELL_NAME"
echo "Using config file: $RCFILE"
echo ""

# Check if rc file exists
if [ ! -f "$RCFILE" ]; then
    echo "Creating $RCFILE..."
    touch "$RCFILE"
fi

echo "Checking for existing Jarvis aliases..."
echo ""
if grep -q "alias jarvis" "$RCFILE" 2>/dev/null; then
    echo "Found existing aliases:"
    grep -n "alias jarvis" "$RCFILE" || true
    echo ""
    read -p "Replace existing aliases? (y/n): " replace
    if [[ "$replace" != "y" && "$replace" != "Y" ]]; then
        echo "Aborted. No changes made."
        exit 0
    fi
    
    # Create backup
    BACKUP="$RCFILE.backup-$(date +%Y%m%d-%H%M%S)"
    cp "$RCFILE" "$BACKUP"
    echo "Backup created: $BACKUP"
    
    # Remove old jarvis aliases
    sed -i '/^alias jarvis/d' "$RCFILE"
    sed -i '/^alias say/d' "$RCFILE"
    sed -i '/^alias question/d' "$RCFILE"
    sed -i '/^# Jarvis Voice Assistant/d' "$RCFILE"
    sed -i '/^# Cloud mode/d' "$RCFILE"
    sed -i '/^# Local mode/d' "$RCFILE"
    sed -i '/^# Quick shortcuts/d' "$RCFILE"
    sed -i '/^# Tools/d' "$RCFILE"
    # Clean up any "# OLD:" commented lines from previous runs
    sed -i '/^# OLD: alias jarvis/d' "$RCFILE"
    sed -i '/^# OLD: alias say/d' "$RCFILE"
    sed -i '/^# OLD: alias question/d' "$RCFILE"
fi

echo ""
echo "Adding Jarvis aliases to $RCFILE..."

# Add new aliases
cat >> "$RCFILE" << 'EOF'

# ============================================================================
# Jarvis Voice Assistant
# ============================================================================

# Cloud mode (uses cloud APIs: Anthropic, xAI, OpenAI, etc.)
alias jarvis="export JARVIS_VENV=$HOME/jarvis-venv UV_PROJECT_ENVIRONMENT=$HOME/jarvis-venv && source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake-jarvis.py"
alias say="$HOME/jarvis-voice/bin/say.sh"
alias question="$HOME/jarvis-voice/bin/question.sh"
alias question-mic="$HOME/jarvis-voice/bin/question-mic.sh"

# Local mode (uses Ollama for LLM, local Whisper for STT)
alias jarvis-local="export JARVIS_VENV=$HOME/jarvis-venv UV_PROJECT_ENVIRONMENT=$HOME/jarvis-venv && source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake-jarvis-local.py"
alias say-local="$HOME/jarvis-voice/bin/say-local.sh"
alias question-local="$HOME/jarvis-voice/bin/question-local.sh"
alias question-mic-local="$HOME/jarvis-voice/bin/question-mic-local.sh"

# Tools
alias jarvis-d="export JARVIS_VENV=$HOME/jarvis-venv UV_PROJECT_ENVIRONMENT=$HOME/jarvis-venv && source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/jarvis-dashboard"
alias jarvis-web="export JARVIS_VENV=$HOME/jarvis-venv UV_PROJECT_ENVIRONMENT=$HOME/jarvis-venv && source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/start web"
alias jarvis-api="export JARVIS_VENV=$HOME/jarvis-venv UV_PROJECT_ENVIRONMENT=$HOME/jarvis-venv && source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/start api"

# Quick shortcuts
alias jarvis-cd="cd $HOME/jarvis-voice"
alias jarvis-env="export JARVIS_VENV=$HOME/jarvis-venv UV_PROJECT_ENVIRONMENT=$HOME/jarvis-venv && source $HOME/jarvis-venv/bin/activate"
alias jarvis-logs="tail -f $HOME/jarvis-voice/logs/*.log"
EOF

echo ""
echo "✅ Aliases added to $RCFILE"
echo ""
echo "Reload with:"
echo "  source $RCFILE"
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
