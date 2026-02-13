#!/bin/bash
# Setup script for Jarvis Tool Calling System
set -e

echo "🔧 Setting up Jarvis Tool Calling System..."
echo

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Make all scripts executable
echo "📝 Making scripts executable..."

# Root level shell scripts
chmod +x *.sh 2>/dev/null || true

# All bin scripts (no extension or any extension)
chmod +x bin/* 2>/dev/null || true

# Core Python directories
chmod +x skills/*.py 2>/dev/null || true
chmod +x orchestrator/*.py 2>/dev/null || true
chmod +x lib/*.py lib/*.sh 2>/dev/null || true
chmod +x services/*.py 2>/dev/null || true
chmod +x api/*.py 2>/dev/null || true

# Web UIs (Flask apps - all nested Python files)
find jarvis-web -name "*.py" -exec chmod +x {} \; 2>/dev/null || true
find jarvis-canvas -name "*.py" -exec chmod +x {} \; 2>/dev/null || true
find jarvis-memory -name "*.py" -exec chmod +x {} \; 2>/dev/null || true
find jarvis-intelligence -name "*.py" -exec chmod +x {} \; 2>/dev/null || true
chmod +x jarvis-monitor/*.py 2>/dev/null || true

# Monitoring
chmod +x monitoring/*.sh 2>/dev/null || true

# Tests
find tests -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true

echo "✅ Scripts are now executable"
echo

# Check Python virtual environment
echo "📦 Checking Python environment..."
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -d "$HOME/jarvis-venv" ]; then
        source ~/jarvis-venv/bin/activate
        echo "✅ Activated ~/jarvis-venv"
    else
        echo "⚠️  No virtual environment active"
        echo "   Create one first: uv venv ~/jarvis-venv && source ~/jarvis-venv/bin/activate"
        exit 1
    fi
else
    echo "✅ Using virtual environment: $VIRTUAL_ENV"
fi
echo

# Verify tool registration
echo "🔍 Verifying tool registry..."
python3 -c "
import sys
sys.path.insert(0, 'lib')
from lib.tool_schema import ToolRegistry
registry = ToolRegistry('skills')
tools = registry.list_tools()
print(f'Registered {len(tools)} tools:')
for tool in tools:
    print(f'  ✓ {tool}')
"

echo
echo "✅ Tool setup complete!"
echo
echo "📚 Next steps:"
echo "  1. Test the orchestrator:"
echo "     ./orchestrator/orchestrator_v2.py cloud 'What time is it?'"
echo
echo "  2. Start all services:"
echo "     ./bin/start"
echo
echo "  3. Or start wake word listener:"
echo "     ./jarvis"
echo
echo "📖 See docs/INSTALL_GUIDE.md for full setup guide"

