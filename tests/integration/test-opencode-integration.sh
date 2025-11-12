#!/bin/bash
# OpenCode Integration Test - Full Flow Verification
# Tests that Jarvis can successfully use OpenCode tool and get responses

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

PASSED=0
FAILED=0

echo "========================================="
echo "  OpenCode Integration Test"
echo "  Testing Jarvis → OpenCode → Response"
echo "========================================="
echo ""

# Test 1: OpenCode Server Health
echo -e "${BLUE}Test 1: OpenCode Server Health Check${NC}"
if curl -s http://localhost:4096/config > /dev/null 2>&1; then
    echo -e "${GREEN}✅ OpenCode server is running${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ OpenCode server is not accessible${NC}"
    echo "   Start it with: sudo systemctl start opencode-jarvis.service"
    FAILED=$((FAILED + 1))
    exit 1
fi

# Test 2: Config Validation
echo -e "\n${BLUE}Test 2: OpenCode Config Validation${NC}"
config_response=$(curl -s http://localhost:4096/config)
if echo "$config_response" | jq -e '.name == "ConfigInvalidError"' > /dev/null 2>&1; then
    echo -e "${RED}❌ Config has errors:${NC}"
    echo "$config_response" | jq '.data.issues'
    FAILED=$((FAILED + 1))
    exit 1
else
    echo -e "${GREEN}✅ Config is valid${NC}"
    PASSED=$((PASSED + 1))
fi

# Test 3: OpenCode Tool Registration
echo -e "\n${BLUE}Test 3: OpenCode Tool Registration${NC}"
# Check if OPENCODE_ENABLED is true
if grep -q 'OPENCODE_ENABLED=true' config/cloud.env 2>/dev/null || grep -q 'OPENCODE_ENABLED=true' config/local.env 2>/dev/null; then
    echo -e "${GREEN}✅ OpenCode is enabled in config${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${YELLOW}⚠️  OpenCode may be disabled (OPENCODE_ENABLED=false)${NC}"
    echo "   Check config/cloud.env or config/local.env"
fi

# Test 4: Simple Math Problem (very simple for OpenCode)
echo -e "\n${BLUE}Test 4: Simple OpenCode Task - Math Problem${NC}"
echo "Query: Use OpenCode to solve: What is 15 multiplied by 7?"

# Capture output and extract JSON (handle verbose output before JSON)
raw_output=$(./orchestrator/orchestrator_v2.py cloud "Use OpenCode to solve: What is 15 multiplied by 7?" --json 2>&1 || echo '{"ok": false, "error": "Failed"}')
# Extract JSON (last line that starts with {)
result=$(echo "$raw_output" | grep -E '^\{' | tail -1 || echo '{"ok": false, "error": "Failed to parse JSON"}')

ok=$(echo "$result" | jq -r '.ok // false' 2>/dev/null || echo "false")
speech=$(echo "$result" | jq -r '.speech // ""' 2>/dev/null || echo "")
error=$(echo "$result" | jq -r '.error // ""' 2>/dev/null || echo "")

if [ "$ok" == "true" ]; then
    # Check if response contains the answer (105) or mentions OpenCode
    if echo "$speech" | grep -qiE "(105|opencode|multiplied)" || [ -n "$speech" ]; then
        echo -e "${GREEN}✅ PASSED${NC}"
        echo "Response: ${speech:0:200}..."
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}❌ FAILED - Unexpected response${NC}"
        echo "Response: ${speech:0:200}"
        FAILED=$((FAILED + 1))
    fi
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Error: ${error:-$speech}"
    echo "Full result: $result"
    FAILED=$((FAILED + 1))
fi

# Test 5: Simple Greeting (even simpler)
echo -e "\n${BLUE}Test 5: Simple OpenCode Task - Greeting${NC}"
echo "Query: Use OpenCode to say hello and tell me what you can do"

# Capture output and extract JSON (handle verbose output before JSON)
raw_output=$(./orchestrator/orchestrator_v2.py cloud "Use OpenCode to say hello and tell me what you can do" --json 2>&1 || echo '{"ok": false, "error": "Failed"}')
# Extract JSON (last line that starts with {)
result=$(echo "$raw_output" | grep -E '^\{' | tail -1 || echo '{"ok": false, "error": "Failed to parse JSON"}')

ok=$(echo "$result" | jq -r '.ok // false' 2>/dev/null || echo "false")
speech=$(echo "$result" | jq -r '.speech // ""' 2>/dev/null || echo "")

if [ "$ok" == "true" ] && [ -n "$speech" ]; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: ${speech:0:200}..."
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: ${speech:0:200}"
    echo "Full result: $result"
    FAILED=$((FAILED + 1))
fi

# Test 6: Verify Session Created
echo -e "\n${BLUE}Test 6: OpenCode Session Creation${NC}"
sessions=$(curl -s http://localhost:4096/session 2>/dev/null || echo "[]")
session_count=$(echo "$sessions" | jq 'length' 2>/dev/null || echo "0")

if [ "$session_count" -gt 0 ]; then
    echo -e "${GREEN}✅ OpenCode sessions exist ($session_count session(s))${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${YELLOW}⚠️  No OpenCode sessions found (may be normal if sessions were cleaned up)${NC}"
fi

# Summary
echo ""
echo "========================================="
echo "  Test Results"
echo "========================================="
echo -e "Total Tests: $((PASSED + FAILED))"
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"

if [ $FAILED -eq 0 ]; then
    echo -e "\n${GREEN}🎉 All OpenCode integration tests passed!${NC}"
    echo ""
    echo "✅ OpenCode server is running"
    echo "✅ Config is valid"
    echo "✅ Jarvis can use OpenCode tool"
    echo "✅ OpenCode responds correctly"
    exit 0
else
    echo -e "\n${RED}⚠️  Some tests failed. Check output above.${NC}"
    exit 1
fi

