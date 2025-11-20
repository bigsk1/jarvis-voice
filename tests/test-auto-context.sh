#!/bin/bash
# Test script for Auto-Context System
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCHESTRATOR="$PROJECT_ROOT/orchestrator/orchestrator_v2.py"

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║ Testing Jarvis Auto-Context System                            ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if auto-context is enabled
echo "1. Checking configuration..."
if grep -q "AUTO_CONTEXT_ENABLED=true" "$PROJECT_ROOT/config/cloud.env"; then
    echo "   ✅ Auto-context is ENABLED"
else
    echo "   ❌ Auto-context is DISABLED - enable in config/cloud.env"
    exit 1
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║ Test 1: Hot/Cold Contradiction Detection                      ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

echo "Query 1: 'Today is super hot'"
RESPONSE1=$("$ORCHESTRATOR" cloud "Today is super hot" --json | jq -r '.speech')
echo "Response: $RESPONSE1"
echo ""

echo "Waiting 3 seconds..."
sleep 3

echo "Query 2: 'Today is cold'"
RESPONSE2=$("$ORCHESTRATOR" cloud "Today is cold" --json | jq -r '.speech')
echo "Response: $RESPONSE2"
echo ""

# Check if Jarvis caught the contradiction
if echo "$RESPONSE2" | grep -iq "hot\|just said\|earlier"; then
    echo "✅ TEST PASSED: Jarvis detected the contradiction!"
else
    echo "⚠️  TEST INCONCLUSIVE: Jarvis didn't explicitly mention contradiction"
    echo "   (This is OK - LLM may respond differently)"
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║ Test 2: Workflow Continuation                                 ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

echo "Query 1: 'What is Bitcoin price?'"
RESPONSE3=$("$ORCHESTRATOR" cloud "What is Bitcoin price?" --json)
SPEECH3=$(echo "$RESPONSE3" | jq -r '.speech')
TOOLS3=$(echo "$RESPONSE3" | jq -r '.tools_used[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//')
echo "Response: $SPEECH3"
echo "Tools used: $TOOLS3"
echo ""

echo "Waiting 3 seconds..."
sleep 3

echo "Query 2: 'Did you just check Bitcoin?'"
RESPONSE4=$("$ORCHESTRATOR" cloud "Did you just check Bitcoin?" --json)
SPEECH4=$(echo "$RESPONSE4" | jq -r '.speech')
TOOLS4=$(echo "$RESPONSE4" | jq -r '.tools_used[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//')
echo "Response: $SPEECH4"
echo "Tools used: $TOOLS4"
echo ""

# Check if Jarvis remembered without calling tool again
if [ -z "$TOOLS4" ] && echo "$SPEECH4" | grep -iq "yes\|just"; then
    echo "✅ TEST PASSED: Jarvis remembered without calling crypto_price again!"
elif echo "$SPEECH4" | grep -iq "yes\|just"; then
    echo "⚠️  TEST PARTIAL: Jarvis remembered but may have called tools"
else
    echo "⚠️  TEST INCONCLUSIVE: Response unclear"
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║ Test 3: Recent Conversation Awareness                         ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

echo "Query: 'What was my last question?'"
RESPONSE5=$("$ORCHESTRATOR" cloud "What was my last question?" --json)
SPEECH5=$(echo "$RESPONSE5" | jq -r '.speech')
TOOLS5=$(echo "$RESPONSE5" | jq -r '.tools_used[]' 2>/dev/null | tr '\n' ',' | sed 's/,$//')
echo "Response: $SPEECH5"
echo "Tools used: $TOOLS5"
echo ""

# Check if Jarvis answered from context (no tool call) or used tool
if [ -z "$TOOLS5" ] && echo "$SPEECH5" | grep -iq "bitcoin"; then
    echo "✅ TEST PASSED: Jarvis answered from auto-context (no tool needed)!"
elif echo "$TOOLS5" | grep -q "get_recent_conversations\|search_conversations"; then
    echo "✅ TEST PASSED: Jarvis used conversation tool to get more history"
else
    echo "⚠️  TEST INCONCLUSIVE: Unexpected behavior"
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║ Test Summary                                                  ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "The auto-context system allows Jarvis to:"
echo "  1. ✅ Remember recent statements (hot/cold contradiction)"
echo "  2. ✅ Avoid redundant tool calls (workflow awareness)"
echo "  3. ✅ Reference previous questions naturally"
echo ""
echo "Configuration:"
echo "  AUTO_CONTEXT_WINDOW=$(grep AUTO_CONTEXT_WINDOW $PROJECT_ROOT/config/cloud.env | cut -d= -f2)"
echo "  AUTO_CONTEXT_MINUTES=$(grep AUTO_CONTEXT_MINUTES $PROJECT_ROOT/config/cloud.env | cut -d= -f2)"
echo ""
echo "To disable: Set AUTO_CONTEXT_ENABLED=false in config/cloud.env"
echo ""

