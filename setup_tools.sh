#!/bin/bash
# Setup script for Jarvis Tool Calling System
set -e

echo "🔧 Setting up Jarvis Tool Calling System..."
echo

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Make Python scripts executable
echo "📝 Making tool scripts executable..."
chmod +x skills/*.py 2>/dev/null || true
chmod +x bin/question-orchestrator.sh
chmod +x bin/question-orchestrator-local.sh
chmod +x orchestrator/*.py
chmod +x lib/*.py

echo "✅ Scripts are now executable"
echo

# Check Python dependencies
echo "📦 Checking Python dependencies..."
source ~/jarvis-venv/bin/activate || {
    echo "❌ Virtual environment not found at ~/jarvis-venv"
    echo "   Please activate your Python virtual environment first"
    exit 1
}

# Install dependencies
echo "Installing required packages..."
pip install --quiet --upgrade anthropic openai requests

echo "✅ Dependencies installed"
echo

# Verify tool registration
echo "🔍 Verifying tool registry..."
python3 -c "
from lib.tool_schema import ToolRegistry
registry = ToolRegistry('skills')
tools = registry.list_tools()
print(f'Registered {len(tools)} tools:')
for tool in tools:
    print(f'  ✓ {tool}')
"

echo
echo "✅ Setup complete!"
echo
echo "📚 Next steps:"
echo "  1. Configure your API key in config/cloud.env"
echo "     Edit: ANTHROPIC_API_KEY=\"your-key-here\""
echo
echo "  2. Test a tool:"
echo "     echo '{}' | ./skills/time.sh"
echo
echo "  3. Test the orchestrator:"
echo "     ./orchestrator/orchestrator_v2.py cloud 'What time is it?'"
echo
echo "  4. Start Jarvis with tools:"
echo "     jarvis"
echo
echo "📖 Read TEST_TOOL_SYSTEM.md for comprehensive testing guide"
echo "📖 Read TOOL_SYSTEM_SUMMARY.md for architecture overview"

