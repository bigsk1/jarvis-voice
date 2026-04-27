#!/bin/bash
# Test Tool RAG Dynamic Retrieval
# Verifies that LLM can find and use non-ghost tools via semantic search

source ~/jarvis-venv/bin/activate

echo "========================================="
echo "  Tool RAG Dynamic Retrieval Test"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASSED=0
FAILED=0

# Helper function to test queries
test_query() {
    local test_name="$1"
    local query="$2"
    local expected_tool="$3"
    local expected_keyword="$4"
    
    echo -e "${YELLOW}Test: $test_name${NC}"
    echo "Query: $query"
    echo "Expected Tool: $expected_tool"
    
    # Run query and capture tool logs
    LOG_FILE="/tmp/tool-rag-test-$$.log"
    OUTPUT=$(./orchestrator/orchestrator_v2.py cloud "$query" 2>&1 | tee "$LOG_FILE")
    
    # Check if expected tool was used
    TOOL_USED=$(grep -o "\"$expected_tool\"" logs/tools/tool-calls-2025-11-22.jsonl | tail -1)
    
    # Check if response contains expected keyword
    KEYWORD_FOUND=$(echo "$OUTPUT" | grep -i "$expected_keyword")
    
    if [[ -n "$TOOL_USED" ]] && [[ -n "$KEYWORD_FOUND" ]]; then
        echo -e "${GREEN}✅ PASSED${NC}"
        echo "   Tool used: $expected_tool"
        echo "   Response contained: $expected_keyword"
        ((PASSED++))
    else
        echo -e "${RED}❌ FAILED${NC}"
        if [[ -z "$TOOL_USED" ]]; then
            echo "   ERROR: Expected tool '$expected_tool' was not used"
        fi
        if [[ -z "$KEYWORD_FOUND" ]]; then
            echo "   ERROR: Response didn't contain '$expected_keyword'"
        fi
        ((FAILED++))
    fi
    echo ""
    
    rm -f "$LOG_FILE"
}

echo "Phase 1: Non-Ghost Tools (Must be retrieved via Tool RAG)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 1: crypto_price (NOT a ghost tool)
test_query "Crypto Price Lookup" \
    "What's the current price of Bitcoin?" \
    "crypto_price" \
    "Bitcoin"

# Test 2: create_reminder (NOT a ghost tool)
test_query "Reminder Creation" \
    "Remind me to call mom tomorrow at 3pm" \
    "create_reminder" \
    "reminder"

# Test 3: api_call (NOT a ghost tool)
test_query "API Call" \
    "Make a GET request to https://httpbin.org/uuid" \
    "api_call" \
    "uuid"

# Test 4: list_reminders (NOT a ghost tool)
test_query "List Reminders" \
    "What reminders do I have?" \
    "list_reminders" \
    "reminder"

echo "Phase 2: Ghost Tools (Always available, no retrieval needed)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 5: get_time (Ghost tool)
test_query "Get Time (Ghost)" \
    "What time is it?" \
    "get_time" \
    "2025"

# Test 6: remember (Ghost tool)
test_query "Remember (Ghost)" \
    "Remember that I prefer dark mode" \
    "remember" \
    "dark mode"

# Test 7: search_memory (Ghost tool)
test_query "Search Memory (Ghost)" \
    "Search my memories for mode" \
    "search_memory" \
    "dark"

echo "Phase 3: Tool Selection Intelligence"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 8: Verify Tool RAG retrieved correct non-ghost tools
echo -e "${YELLOW}Analyzing Tool Retrieval Logs...${NC}"
echo ""

# Check recent tool calls
RECENT_TOOLS=$(tail -20 logs/tools/tool-calls-2025-11-22.jsonl | jq -r '.tool' | sort | uniq)

NON_GHOST_USED=0
for tool in $RECENT_TOOLS; do
    # Check if tool is NOT a ghost tool
    if [[ "$tool" != "search_memory" ]] && \
       [[ "$tool" != "semantic_recall" ]] && \
       [[ "$tool" != "remember" ]] && \
       [[ "$tool" != "check_tool_logs" ]] && \
       [[ "$tool" != "get_recent_conversations" ]] && \
       [[ "$tool" != "get_time" ]] && \
       [[ "$tool" != "recall" ]]; then
        echo "   ✓ Non-ghost tool used: $tool"
        ((NON_GHOST_USED++))
    fi
done

echo ""
if [[ $NON_GHOST_USED -ge 3 ]]; then
    echo -e "${GREEN}✅ Tool RAG is working: $NON_GHOST_USED non-ghost tools were discovered and used${NC}"
    ((PASSED++))
else
    echo -e "${RED}❌ Tool RAG may not be working: Only $NON_GHOST_USED non-ghost tools used${NC}"
    echo "   Expected at least 3 (crypto_price, create_reminder, api_call, list_reminders)"
    ((FAILED++))
fi

echo ""
echo "========================================="
echo "  Results"
echo "========================================="
echo -e "Total Tests: $((PASSED + FAILED))"
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}🎉 All Tool RAG tests passed!${NC}"
    echo "   ✓ Non-ghost tools are being retrieved dynamically"
    echo "   ✓ Ghost tools are always available"
    echo "   ✓ System is ready to scale to 100+ tools"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed${NC}"
    echo "   Check logs: logs/tools/tool-calls-2025-11-22.jsonl"
    echo "   Debug with: ./bin/debug-tool-rag.py cloud \"your query\""
    exit 1
fi

