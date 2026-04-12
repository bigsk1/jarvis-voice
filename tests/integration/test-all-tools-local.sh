#!/bin/bash
# Comprehensive Jarvis Tool Testing Script - LOCAL MODE (Ollama)
# Tests using qwen3-vl model
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
    
    # Run test with longer timeout for Ollama (60s)
    result=$(timeout 60 ./orchestrator/orchestrator_v2.py local "$query" --json 2>/dev/null || echo '{"ok": false}')
    
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
        echo "Full result: $result"
        FAILED=$((FAILED + 1))
    fi
}

# Load local config to get OLLAMA_BASE_URL
source config/local.env

echo "========================================="
echo "  Jarvis Local Tool Testing (Ollama)"
echo -e "${BLUE}  Model: $OLLAMA_MODEL${NC}"
echo "========================================="



# Check if Ollama is running (use configured fallback order)
declare -a OLLAMA_URLS=()
declare -A OLLAMA_SEEN=()
OLLAMA_URL=""

IFS=',' read -r -a OLLAMA_RAW_URLS <<< "${OLLAMA_BASE_URL:-http://localhost:11434},http://localhost:11434"
for candidate in "${OLLAMA_RAW_URLS[@]}"; do
    candidate="$(echo "$candidate" | xargs)"
    candidate="${candidate%/}"
    [ -z "$candidate" ] && continue
    [ -n "${OLLAMA_SEEN[$candidate]:-}" ] && continue
    OLLAMA_SEEN["$candidate"]=1
    OLLAMA_URLS+=("$candidate")
done

for candidate in "${OLLAMA_URLS[@]}"; do
    echo -e "${BLUE}Checking Ollama at: $candidate${NC}"
    if curl --connect-timeout 2 --max-time 5 -s "$candidate/api/tags" &>/dev/null; then
        OLLAMA_URL="$candidate"
        break
    fi
done

if [ -z "$OLLAMA_URL" ]; then
    echo -e "${RED}❌ Ollama is not reachable at any configured host${NC}"
    printf 'Tried: %s\n' "${OLLAMA_URLS[*]}"
    exit 1
fi

# Check if qwen3-vl is available on remote
if ! curl -s "$OLLAMA_URL/api/tags" | jq -r '.models[].name' | grep -q "qwen3-vl"; then
    echo -e "${RED}❌ qwen3-vl model not found on remote server!${NC}"
    echo "Pull it on the remote server with: ollama pull qwen3-vl"
    exit 1
fi

echo -e "${GREEN}✅ Ollama is running at $OLLAMA_URL${NC}"
echo -e "${GREEN}✅ $OLLAMA_MODEL model is available${NC}"

# Warm up MCP servers (they need time to start)
echo -e "\n${YELLOW}Warming up MCP servers...${NC}"
sleep 5  # Longer warmup for local mode

echo -e "\n${BLUE}=== LOCAL TOOLS ===${NC}"

# 1. Time
test_tool "get_time" \
    "The following questions will be a test of tool and mcp usage. What time is it?" \
    "M"  # Will contain AM or PM

# 2. Date
test_tool "get_time (date)" \
    "What's the date today?" \
    "2025"  # Will contain year

# 3. Crypto Price  
test_tool "crypto_price" \
    "What's the Bitcoin price?" \
    "Bitcoin"  # Will mention Bitcoin

# 4. API Call (simple GET)
test_tool "api_call" \
    "Make a GET request to https://httpbin.org/get" \
    "httpbin"  # Response will mention httpbin

echo -e "\n${BLUE}=== MEMORY TOOLS ===${NC}"

# 5. Remember
test_tool "remember" \
    "Remember that my favorite color is blue" \
    "blue"  # Confirmation mentions the saved value

# 6. Recall  
test_tool "recall" \
    "What's my favorite color?" \
    "blue"  # Should recall blue

# 7. Search Memory
test_tool "search_memory" \
    "Search my memories for color" \
    "blue"  # Should find blue memory

# 8. Semantic Recall
test_tool "semantic_recall" \
    "What do I like that's a shade or hue?" \
    "blue"  # Should find blue via semantic search

# 9. Update Memory
test_tool "update_memory" \
    "Actually my favorite color is green now" \
    "green"  # Should mention green

# 10. Forget
test_tool "forget" \
    "Forget what my favorite color is" \
    "color"  # Will mention clearing/forgetting color

echo -e "\n${BLUE}=== MCP TOOLS ===${NC}"

# Give MCP servers extra time
echo "Ensuring MCP servers are ready..."
sleep 3

# 11. MCP Brave Web Search
test_tool "mcp_brave_web_search" \
    "Use brave web search to find Ollama AI" \
    "Ollama"  # Results will mention Ollama

# 12. MCP Fetch
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
    echo -e "\n${BLUE}Note: Local mode uses Ollama (qwen3-vl) and is slower than cloud mode.${NC}"
    exit 0
else
    echo -e "\n${RED}⚠️  Some tests failed. Check output above.${NC}"
    echo -e "\n${BLUE}Tip: Local LLMs may interpret queries differently. Check if the tool was called correctly.${NC}"
    exit 1
fi
