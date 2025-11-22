#!/bin/bash
# Test Multi-Turn Self-Healing
# Verifies LLM can diagnose and fix errors through multiple tool calls

source ~/jarvis-venv/bin/activate

echo "========================================="
echo "  Multi-Turn Self-Healing Test"
echo "========================================="
echo ""
echo "This test verifies the LLM can:"
echo "  1. Attempt a task that will fail"
echo "  2. Check logs to understand the error"
echo "  3. Retry with corrected parameters"
echo "  4. Succeed on subsequent attempts"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Test scenarios
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Scenario 1: API Call with Wrong Parameter (Should Self-Correct)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${BLUE}Query:${NC} Make a GET request to httpbin.org/status/999"
echo -e "${YELLOW}Expected behavior:${NC}"
echo "  Turn 1: Try GET to /status/999 → Fail (999 is invalid HTTP status)"
echo "  Turn 2: Check logs or try alternative"
echo "  Turn 3: Either explain error OR try valid endpoint"
echo ""

LOG_START=$(wc -l < logs/tools/tool-calls-2025-11-22.jsonl)

OUTPUT=$(./orchestrator/orchestrator_v2.py cloud "Make a GET request to httpbin.org/status/999" 2>&1)

LOG_END=$(wc -l < logs/tools/tool-calls-2025-11-22.jsonl)
TURNS=$((LOG_END - LOG_START))

echo -e "${BLUE}Response:${NC} $OUTPUT"
echo ""
echo -e "${YELLOW}Analysis:${NC}"
echo "  Tool calls in this session: $TURNS"

# Extract tool names used
TOOLS_USED=$(tail -$TURNS logs/tools/tool-calls-2025-11-22.jsonl | jq -r '.tool' | tr '\n' ', ' | sed 's/,$//')
echo "  Tools used: $TOOLS_USED"

# Check if LLM checked logs or understood the error
CHECK_LOGS=$(tail -$TURNS logs/tools/tool-calls-2025-11-22.jsonl | jq -r 'select(.tool=="check_tool_logs") | .tool' | wc -l)
if [ $CHECK_LOGS -gt 0 ]; then
    echo -e "  ${GREEN}✅ LLM checked logs to diagnose the error${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Scenario 2: Crypto Price with Typo (Should Auto-Correct)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${BLUE}Query:${NC} What's the price of 'bitcon' (intentional typo)"
echo -e "${YELLOW}Expected behavior:${NC}"
echo "  Turn 1: Try 'bitcon' → Fail (not found)"
echo "  Turn 2: Understand error mentions valid coins"
echo "  Turn 3: Retry with 'bitcoin' OR explain error"
echo ""

LOG_START=$(wc -l < logs/tools/tool-calls-2025-11-22.jsonl)

OUTPUT=$(./orchestrator/orchestrator_v2.py cloud "What's the current price of bitcon?" 2>&1)

LOG_END=$(wc -l < logs/tools/tool-calls-2025-11-22.jsonl)
TURNS=$((LOG_END - LOG_START))

echo -e "${BLUE}Response:${NC} $OUTPUT"
echo ""
echo -e "${YELLOW}Analysis:${NC}"
echo "  Tool calls in this session: $TURNS"

TOOLS_USED=$(tail -$TURNS logs/tools/tool-calls-2025-11-22.jsonl | jq -r '.tool' | tr '\n' ', ' | sed 's/,$//')
echo "  Tools used: $TOOLS_USED"

# Check if it retried with correct spelling
RETRIES=$(tail -$TURNS logs/tools/tool-calls-2025-11-22.jsonl | jq -r 'select(.tool=="crypto_price") | .arguments.coin' | grep -i bitcoin | wc -l)
if [ $RETRIES -gt 0 ]; then
    echo -e "  ${GREEN}✅ LLM auto-corrected the typo and retried${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Scenario 3: Memory Search Fallback Chain"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "First, save a memory..."
./orchestrator/orchestrator_v2.py cloud "Remember that my favorite color is purple" > /dev/null 2>&1
sleep 1

echo -e "${BLUE}Query:${NC} What color do I prefer?"
echo -e "${YELLOW}Expected behavior:${NC}"
echo "  Turn 1: Try semantic_recall → May fail (fresh embedding)"
echo "  Turn 2: Fallback to search_memory → Should find 'color'"
echo "  Turn 3: Return answer with 'purple'"
echo ""

LOG_START=$(wc -l < logs/tools/tool-calls-2025-11-22.jsonl)

OUTPUT=$(./orchestrator/orchestrator_v2.py cloud "What color do I prefer?" 2>&1)

LOG_END=$(wc -l < logs/tools/tool-calls-2025-11-22.jsonl)
TURNS=$((LOG_END - LOG_START))

echo -e "${BLUE}Response:${NC} $OUTPUT"
echo ""
echo -e "${YELLOW}Analysis:${NC}"
echo "  Tool calls in this session: $TURNS"

TOOLS_USED=$(tail -$TURNS logs/tools/tool-calls-2025-11-22.jsonl | jq -r '.tool' | tr '\n' ', ' | sed 's/,$//')
echo "  Tools used: $TOOLS_USED"

# Check if it used multiple memory tools
MEMORY_TOOLS=$(tail -$TURNS logs/tools/tool-calls-2025-11-22.jsonl | jq -r 'select(.tool=="semantic_recall" or .tool=="search_memory" or .tool=="recall") | .tool')
MEMORY_COUNT=$(echo "$MEMORY_TOOLS" | grep -v '^$' | wc -l)

if [ $MEMORY_COUNT -gt 1 ]; then
    echo -e "  ${GREEN}✅ LLM used fallback strategy (tried multiple memory tools)${NC}"
    echo "  Memory tools used:"
    echo "$MEMORY_TOOLS" | grep -v '^$' | sort | uniq -c | sed 's/^/    /'
fi

# Check if answer contains "purple"
if echo "$OUTPUT" | grep -qi "purple"; then
    echo -e "  ${GREEN}✅ Successfully found and returned the answer${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Summary: Multi-Turn Self-Healing Capabilities"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "The LLM demonstrated:"
echo ""

# Count total log checking
TOTAL_LOG_CHECKS=$(tail -100 logs/tools/tool-calls-2025-11-22.jsonl | jq -r 'select(.tool=="check_tool_logs") | .tool' | wc -l)
if [ $TOTAL_LOG_CHECKS -gt 0 ]; then
    echo -e "${GREEN}✅ Self-diagnosis: Used check_tool_logs to understand failures${NC}"
else
    echo -e "${YELLOW}⚠️  Did not explicitly check logs (may have used error context directly)${NC}"
fi

# Check for retries
TOTAL_RETRIES=$(tail -100 logs/tools/tool-calls-2025-11-22.jsonl | jq -r '.tool' | sort | uniq -c | awk '$1 > 1 {print $2}' | wc -l)
if [ $TOTAL_RETRIES -gt 0 ]; then
    echo -e "${GREEN}✅ Persistence: Retried failed operations${NC}"
fi

# Check for tool switching
UNIQUE_TOOLS=$(tail -100 logs/tools/tool-calls-2025-11-22.jsonl | jq -r '.tool' | sort | uniq | wc -l)
if [ $UNIQUE_TOOLS -gt 3 ]; then
    echo -e "${GREEN}✅ Adaptability: Used multiple different tools ($UNIQUE_TOOLS unique tools)${NC}"
fi

echo ""
echo -e "${BLUE}Full tool usage in this session:${NC}"
tail -100 logs/tools/tool-calls-2025-11-22.jsonl | jq -r '.tool' | sort | uniq -c | sed 's/^/  /'

echo ""
echo "To see detailed turn-by-turn analysis:"
echo "  tail -50 logs/tools/tool-calls-2025-11-22.jsonl | jq -r '[.timestamp, .tool, .result.ok, .result.speech] | @tsv'"

