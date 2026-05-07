#!/bin/bash
# Hard Intelligence Test Cases
# Tests complex scenarios that require proper tool selection

set -e
cd "$(dirname "$0")/../.."
source ~/jarvis-venv/bin/activate

echo "=============================================="
echo "🧠 HARD INTELLIGENCE TESTS"
echo "=============================================="
echo "These tests challenge the reflection system with"
echo "complex scenarios where wrong tools are likely."
echo ""

MODE="${1:-cloud}"
echo "Mode: $MODE"
echo ""

# Track results
PASS=0
FAIL=0

test_scenario() {
    local name="$1"
    local query="$2"
    local expected_pattern="$3"
    local should_use_memory="${4:-false}"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "TEST: $name"
    echo "Query: $query"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    OUTPUT=$(./orchestrator/orchestrator_v2.py "$MODE" "$query" 2>&1)
    
    # Check if expected pattern is in response
    if echo "$OUTPUT" | grep -qi "$expected_pattern"; then
        echo "✅ PASSED - Found expected pattern"
        ((PASS++))
    else
        echo "❌ FAILED - Expected pattern not found: $expected_pattern"
        echo "Response preview: $(echo "$OUTPUT" | grep -A5 "speech" | head -6)"
        ((FAIL++))
    fi
    
    # Check memory tool usage if required
    if [ "$should_use_memory" = "true" ]; then
        if echo "$OUTPUT" | grep -q '"tools_used".*search_memory\|semantic_recall\|recall'; then
            echo "✅ Memory tool was used (correct)"
        else
            echo "⚠️  Memory tool was NOT used (may be suboptimal)"
        fi
    fi
    
    echo ""
    sleep 2
}

echo "=============================================="
echo "CATEGORY 1: Personal Server Status (should check memory)"
echo "=============================================="

test_scenario \
    "Ollama Server Check - Wrong IP Provided" \
    "Is my Ollama server at 203.0.113.250 running?" \
    "running\|not running\|connection\|failed" \
    "true"

test_scenario \
    "Generic Server Status - Memory Has Details" \
    "Is my main AI server running?" \
    "running\|ollama\|192.168" \
    "true"

test_scenario \
    "Service Health Check with Memory Context" \
    "Check if my API service is healthy" \
    "health\|running\|status" \
    "true"

echo "=============================================="
echo "CATEGORY 2: Ambiguous Queries (requires judgment)"
echo "=============================================="

test_scenario \
    "Price Query - Direct Tool Best" \
    "What's Bitcoin worth right now?" \
    "bitcoin\|BTC\|\$[0-9]" \
    "false"

test_scenario \
    "Combined Query - Memory + Action" \
    "What's Bitcoin price and do I have any crypto investments stored?" \
    "bitcoin\|price\|investment\|memory" \
    "true"

test_scenario \
    "Ambiguous 'My' Query" \
    "What's on my todo list?" \
    "reminder\|todo\|list\|alert" \
    "true"

echo "=============================================="
echo "CATEGORY 3: Multi-Step Tasks"
echo "=============================================="

test_scenario \
    "Save and Verify" \
    "Remember my favorite color is blue, then confirm you saved it" \
    "blue\|saved\|remembered" \
    "false"

test_scenario \
    "Search Then Summarize" \
    "Search the web for latest AI news and give me a brief summary" \
    "AI\|news\|summary" \
    "false"

echo "=============================================="
echo "CATEGORY 4: Edge Cases"
echo "=============================================="

test_scenario \
    "Empty Memory Search Then Action" \
    "What's the status of my nonexistent-server-12345?" \
    "not found\|no information\|don't have" \
    "true"

test_scenario \
    "Time-Sensitive vs Memory" \
    "What time is it and when is my next reminder?" \
    "time\|reminder\|[0-9]:[0-9]" \
    "false"

echo "=============================================="
echo "RESULTS SUMMARY"
echo "=============================================="
echo "Passed: $PASS"
echo "Failed: $FAIL"
TOTAL=$((PASS + FAIL))
echo "Total:  $TOTAL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "🎉 All tests passed!"
    exit 0
else
    echo "⚠️  Some tests failed. Check logs for details."
    echo ""
    echo "After running, trigger reflection to learn from these:"
    echo "  curl -X POST 'http://localhost:8880/api/intelligence/reflect?batch_size=20'"
    exit 1
fi

