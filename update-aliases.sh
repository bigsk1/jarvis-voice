#!/bin/bash
# Script to safely update .bashrc aliases for new Jarvis structure

set -e

echo "======================================"
echo "  Update Jarvis Aliases"
echo "======================================"
echo ""

BASHRC="$HOME/.bashrc"

# Check if .bashrc exists
if [ ! -f "$BASHRC" ]; then
    echo "❌ ~/.bashrc not found"
    exit 1
fi

echo "📋 Current Jarvis aliases in ~/.bashrc:"
echo ""
grep -n "alias jarvis" "$BASHRC" || echo "   (none found)"
echo ""

# Create backup
BACKUP="$HOME/.bashrc.backup-$(date +%Y%m%d-%H%M%S)"
cp "$BASHRC" "$BACKUP"
echo "✅ Backup created: $BACKUP"
echo ""

# Offer options
echo "Choose an option:"
echo ""
echo "1) UPDATE aliases to point to new structure (recommended)"
echo "2) COMMENT OUT old aliases (keeps them for reference)"
echo "3) EXIT without changes"
echo ""
read -p "Enter choice (1-3): " choice

case $choice in
    1)
        echo ""
        echo "Updating aliases..."
        
        # Comment out old aliases
        sed -i 's/^alias jarvis=/# OLD: alias jarvis=/g' "$BASHRC"
        sed -i 's/^alias jarvis-local=/# OLD: alias jarvis-local=/g' "$BASHRC"
        sed -i 's/^alias say=/# OLD: alias say=/g' "$BASHRC"
        sed -i 's/^alias say-local=/# OLD: alias say-local=/g' "$BASHRC"
        sed -i 's/^alias question=/# OLD: alias question=/g' "$BASHRC"
        sed -i 's/^alias question-mic=/# OLD: alias question-mic=/g' "$BASHRC"
        sed -i 's/^alias question-local=/# OLD: alias question-local=/g' "$BASHRC"
        sed -i 's/^alias question-mic-local=/# OLD: alias question-mic-local=/g' "$BASHRC"
        
        # Add new aliases
        cat >> "$BASHRC" << 'EOF'

# Jarvis Voice Assistant - Structured Project (Updated $(date +%Y-%m-%d))
# Cloud mode
alias jarvis="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis.py"
alias say="$HOME/jarvis-voice/bin/say.sh"
alias question="$HOME/jarvis-voice/bin/question.sh"
alias question-mic="$HOME/jarvis-voice/bin/question-mic.sh"

# Local mode
alias jarvis-local="source $HOME/jarvis-venv/bin/activate && cd $HOME/jarvis-voice && ./bin/wake_jarvis_local.py"
alias say-local="$HOME/jarvis-voice/bin/say-local.sh"
alias question-local="$HOME/jarvis-voice/bin/question-local.sh"
alias question-mic-local="$HOME/jarvis-voice/bin/question-mic-local.sh"

# Quick shortcuts
alias jarvis-cd="cd $HOME/jarvis-voice"
alias jarvis-env="source $HOME/jarvis-venv/bin/activate"
EOF
        
        echo "✅ Aliases updated!"
        echo ""
        echo "Reload with: source ~/.bashrc"
        ;;
        
    2)
        echo ""
        echo "Commenting out old aliases..."
        
        sed -i 's/^alias jarvis=/# OLD: alias jarvis=/g' "$BASHRC"
        sed -i 's/^alias jarvis-local=/# OLD: alias jarvis-local=/g' "$BASHRC"
        sed -i 's/^alias say=/# OLD: alias say=/g' "$BASHRC"
        sed -i 's/^alias say-local=/# OLD: alias say-local=/g' "$BASHRC"
        sed -i 's/^alias question=/# OLD: alias question=/g' "$BASHRC"
        sed -i 's/^alias question-mic=/# OLD: alias question-mic=/g' "$BASHRC"
        sed -i 's/^alias question-local=/# OLD: alias question-local=/g' "$BASHRC"
        sed -i 's/^alias question-mic-local=/# OLD: alias question-mic-local=/g' "$BASHRC"
        
        echo "✅ Old aliases commented out"
        echo ""
        echo "You can now use the new structure with explicit paths."
        echo "Reload with: source ~/.bashrc"
        ;;
        
    3)
        echo ""
        echo "No changes made."
        exit 0
        ;;
        
    *)
        echo "Invalid choice. No changes made."
        exit 1
        ;;
esac

echo ""
echo "======================================"
echo "New aliases (copy manually if needed):"
echo "======================================"
cat "$HOME/jarvis-voice/.bashrc-aliases"

