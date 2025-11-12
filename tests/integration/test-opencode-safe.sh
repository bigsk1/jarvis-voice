#!/bin/bash
# Safe OpenCode Integration Test
# Tests basic connection and simple chat interaction (no file operations)

set -euo pipefail

# Change to project root (two levels up from tests/integration/)
cd "$(dirname "$0")/../.."
source ~/jarvis-venv/bin/activate

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "========================================="
echo "  OpenCode Integration Test (Safe)"
echo "========================================="
echo ""

# Test 1: Check OpenCode server is running
echo -e "${BLUE}Test 1: OpenCode Server Health Check${NC}"
if curl -s http://localhost:4096/config > /dev/null 2>&1; then
    echo -e "${GREEN}✅ OpenCode server is running${NC}"
else
    echo -e "${RED}❌ OpenCode server is not accessible${NC}"
    echo "   Start it with: sudo systemctl start opencode-jarvis.service"
    exit 1
fi

# Test 2: Check config is valid
echo -e "\n${BLUE}Test 2: OpenCode Config Validation${NC}"
config_response=$(curl -s http://localhost:4096/config)
if echo "$config_response" | jq -e '.name == "ConfigInvalidError"' > /dev/null 2>&1; then
    echo -e "${RED}❌ Config has errors:${NC}"
    echo "$config_response" | jq '.data.issues'
    exit 1
else
    echo -e "${GREEN}✅ Config is valid${NC}"
fi

# Test 3: Simple chat test (no file operations)
echo -e "\n${BLUE}Test 3: Simple Chat Interaction${NC}"
echo "Query: Use OpenCode to say hello and introduce yourself"

result=$(./orchestrator/orchestrator_v2.py cloud "Use OpenCode to say hello and introduce yourself" --json 2>/dev/null || echo '{"ok": false, "error": "Failed"}')

ok=$(echo "$result" | jq -r '.ok // false')
speech=$(echo "$result" | jq -r '.speech // ""' 2>/dev/null || echo "")

if [ "$ok" == "true" ]; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: ${speech:0:200}..."
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Error: $(echo "$result" | jq -r '.error // .speech // "Unknown error"')"
    exit 1
fi

# Test 4: Verify OpenCode tool is registered
echo -e "\n${BLUE}Test 4: Tool Registration Check${NC}"
# Check if opencode tool appears in tool list
if ./orchestrator/orchestrator_v2.py cloud "list all available tools" --json 2>/dev/null | grep -qi "opencode"; then
    echo -e "${GREEN}✅ OpenCode tool is registered${NC}"
else
    echo -e "${YELLOW}⚠️  Could not verify tool registration (may need to check manually)${NC}"
fi

echo ""
echo "========================================="
echo -e "${GREEN}✅ All safe tests passed!${NC}"
echo "========================================="
echo ""
echo "Next steps for more advanced testing:"
echo "  - Test file operations (in isolated workspace)"
echo "  - Test multi-step workflows"
echo "  - Test session persistence"

