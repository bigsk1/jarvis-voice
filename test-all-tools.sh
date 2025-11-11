#!/bin/bash
# Comprehensive Jarvis Tool Testing Script
set -euo pipefail

cd "$(dirname "$0")"
source ~/jarvis-venv/bin/activate

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
PASSED=0
FAILED=0
TOTAL=0

# Test function
test_tool() {
    local name="$1"
    local query="$2"
    local expected="$3"
    
    TOTAL=$((TOTAL + 1))
    echo -e "\n${YELLOW}Test $TOTAL: $name${NC}"
    echo "Query: $query"
    
    # Run test
    result=$(./orchestrator/orchestrator_v2.py cloud "$query" --json 2>/dev/null || echo '{"ok": false}')
    
    # Check if succeeded
    ok=$(echo "$result" | jq -r '.ok')
    speech=$(echo "$result" | jq -r '.speech' 2>/dev/null || echo "")
    
    if [ "$ok" == "true" ] && echo "$speech" | grep -qi "$expected"; then
        echo -e "${GREEN}✅ PASSED${NC}"
        echo "Response: ${speech:0:100}..."
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}❌ FAILED${NC}"
        echo "Expected keyword: $expected"
        echo "Got: ${speech:0:200}"
        FAILED=$((FAILED + 1))
    fi
}

echo "========================================="
echo "  Jarvis Comprehensive Tool Testing"
echo "========================================="

# Warm up MCP servers (they need time to start)
echo -e "\n${YELLOW}Warming up MCP servers...${NC}"
sleep 3

echo -e "\n${YELLOW}=== LOCAL TOOLS ===${NC}"

# 1. Time
test_tool "get_time" \
    "What time is it?" \
    "M"  # Will contain AM or PM

# 2. Crypto Price  
test_tool "crypto_price" \
    "What's the Bitcoin price?" \
    "USD"  # Will contain price in USD

# 3. API Call (simple GET)
test_tool "api_call" \
    "Make a GET request to https://httpbin.org/get" \
    "httpbin"  # Response will mention httpbin

echo -e "\n${YELLOW}=== MEMORY TOOLS ===${NC}"

# 4. Remember
test_tool "remember" \
    "Remember that I love pizza" \
    "remember"  # Confirmation mentions remembering

# 5. Recall  
test_tool "recall" \
    "What food do I love?" \
    "pizza"  # Should recall pizza

# 6. Search Memory
test_tool "search_memory" \
    "Search my memories for food" \
    "pizza"  # Should find pizza memory

# 7. Update Memory
test_tool "update_memory" \
    "Actually I love sushi now, not pizza" \
    "sushi"  # Should mention sushi

# 8. Forget
test_tool "forget" \
    "Forget what food I love" \
    "forgot"  # Confirmation of forgetting

echo -e "\n${YELLOW}=== MCP TOOLS ===${NC}"

# Give MCP servers extra time
echo "Ensuring MCP servers are ready..."
sleep 2

# 9. MCP DuckDuckGo Search
test_tool "mcp_duckduckgo_search" \
    "Use DuckDuckGo to search for OpenAI" \
    "OpenAI"  # Results will mention OpenAI

# 10. MCP Fetch
test_tool "mcp_fetch_fetch" \
    "Use the fetch tool to get content from example.com" \
    "example"  # Will mention example.com

echo -e "\n========================================="
echo "  Test Results"
echo "========================================="
echo -e "Total Tests: $TOTAL"
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"

if [ $FAILED -eq 0 ]; then
    echo -e "\n${GREEN}🎉 All tests passed!${NC}"
    exit 0
else
    echo -e "\n${RED}⚠️  Some tests failed. Check output above.${NC}"
    exit 1
fi

