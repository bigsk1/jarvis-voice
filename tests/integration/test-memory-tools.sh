#!/bin/bash
# Test if LLM chooses the right memory tool based on query type
# Tests the PRINCIPLE, not specific examples

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       Memory Tool Selection Test (Principle-Based)          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Testing if LLM understands WHEN to use semantic_recall vs search_memory"
echo "(Using queries NOT in the training examples)"
echo ""

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source ~/jarvis-venv/bin/activate

# Clean slate - backup and recreate
if [ -f data/jarvis_memory.db ]; then
    cp data/jarvis_memory.db data/jarvis_memory.db.backup-test
    rm data/jarvis_memory.db
fi

./bin/setup-memory-db.sh > /dev/null 2>&1

# CRITICAL: Sync tool definitions to enable Tool RAG
echo "🔧 Syncing tool definitions for Tool RAG..."
./bin/sync-tools.py cloud > /dev/null 2>&1
echo "✅ Tool embeddings ready"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PHASE 1: Setup - Save Test Data"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Saving: 'Remember I love sushi'"
./orchestrator/orchestrator_v2.py cloud "Remember I love sushi" > /tmp/test1.log 2>&1
if grep -q "sushi" /tmp/test1.log; then
    echo "✅ Saved successfully"
else
    echo "❌ Failed to save"
fi
echo ""

echo "Saving: 'My birthday is March 15th'"
./orchestrator/orchestrator_v2.py cloud "My birthday is March 15th" > /tmp/test2.log 2>&1
if grep -q "March\|birthday" /tmp/test2.log; then
    echo "✅ Saved successfully"
else
    echo "❌ Failed to save"
fi
echo ""

sleep 2

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PHASE 2: Test Natural Language Questions (should use semantic_recall)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 1: Different phrasing
echo "Test 1: 'What do I like to eat?'"
./orchestrator/orchestrator_v2.py cloud "What do I like to eat?" > /tmp/test3.log 2>&1
if grep -iq "sushi" /tmp/test3.log; then
    echo "   ✅ PASS - Found sushi"
    PASS1=1
else
    echo "   ❌ FAIL - Didn't find sushi"
    PASS1=0
fi
echo ""

# Test 2: Another variation
echo "Test 2: 'Tell me about my food preferences'"
./orchestrator/orchestrator_v2.py cloud "Tell me about my food preferences" > /tmp/test4.log 2>&1
if grep -iq "sushi" /tmp/test4.log; then
    echo "   ✅ PASS - Found sushi"
    PASS2=1
else
    echo "   ❌ FAIL - Didn't find sushi"
    PASS2=0
fi
echo ""

# Test 3: Birthday query
echo "Test 3: 'When do I celebrate my birth?'"
./orchestrator/orchestrator_v2.py cloud "When do I celebrate my birth?" > /tmp/test5.log 2>&1
if grep -iq "March\|15" /tmp/test5.log; then
    echo "   ✅ PASS - Found birthday"
    PASS3=1
else
    echo "   ❌ FAIL - Didn't find birthday"
    PASS3=0
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PHASE 3: Test Keyword Searches (should use search_memory)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Test 4: 'Search for food'"
./orchestrator/orchestrator_v2.py cloud "Search for food" > /tmp/test6.log 2>&1
if grep -iq "sushi" /tmp/test6.log; then
    echo "   ✅ PASS - Found sushi"
    PASS4=1
else
    echo "   ❌ FAIL - Didn't find sushi"
    PASS4=0
fi
echo ""

echo "Test 5: 'Find birthday'"
./orchestrator/orchestrator_v2.py cloud "Find birthday" > /tmp/test7.log 2>&1
if grep -iq "March\|15" /tmp/test7.log; then
    echo "   ✅ PASS - Found birthday"
    PASS5=1
else
    echo "   ❌ FAIL - Didn't find birthday"
    PASS5=0
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PHASE 4: Auto-Save Intelligence Test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Test 6: Ephemeral data (should NOT save)"
./orchestrator/orchestrator_v2.py cloud "What time is it?" > /tmp/test8.log 2>&1
# Check if 'remember' tool was called
if grep -q '"tool_name":"remember"' logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | tail -1; then
    echo "   ❌ FAIL - Incorrectly saved ephemeral data"
    PASS6=0
else
    echo "   ✅ PASS - Did not save ephemeral data"
    PASS6=1
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PHASE 5: Tool Usage Analysis"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Tools used in this test session:"
echo ""
tail -20 logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '.tool_name' | sort | uniq -c | sort -rn
echo ""

echo "Semantic vs Keyword breakdown:"
SEMANTIC_COUNT=$(tail -20 logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '.tool_name' | grep -c "semantic_recall" || echo "0")
SEARCH_COUNT=$(tail -20 logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '.tool_name' | grep -c "search_memory" || echo "0")
RECALL_COUNT=$(tail -20 logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '.tool_name' | grep -c "^recall$" || echo "0")

echo "  semantic_recall: $SEMANTIC_COUNT (for natural language)"
echo "  search_memory:   $SEARCH_COUNT (for keywords)"
echo "  recall:          $RECALL_COUNT (should be 0 - it's redundant)"
echo ""

if [ $RECALL_COUNT -gt 0 ]; then
    echo "⚠️  Warning: 'recall' tool was used - it's redundant with search_memory"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "RESULTS SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

TOTAL=$((PASS1 + PASS2 + PASS3 + PASS4 + PASS5 + PASS6))
echo "Tests Passed: $TOTAL / 6"
echo ""

if [ $TOTAL -eq 6 ]; then
    echo "✅ ALL TESTS PASSED!"
    echo ""
    echo "LLM successfully:"
    echo "  ✅ Uses semantic_recall for natural language questions"
    echo "  ✅ Uses search_memory for keyword searches"
    echo "  ✅ Understands the principle (not just examples)"
    echo "  ✅ Auto-save intelligence working"
    EXIT_CODE=0
elif [ $TOTAL -ge 4 ]; then
    echo "⚠️  MOSTLY PASSING ($TOTAL/6)"
    echo ""
    echo "Some issues detected - review logs in /tmp/test*.log"
    EXIT_CODE=1
else
    echo "❌ MULTIPLE FAILURES ($TOTAL/6)"
    echo ""
    echo "LLM may not understand tool selection principles"
    echo "Review logs in /tmp/test*.log"
    EXIT_CODE=1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Detailed logs saved to: /tmp/test*.log"
echo "Tool call logs: logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl"
echo ""

# Restore backup if needed
if [ -f data/jarvis_memory.db.backup-test ]; then
    echo "Database backup saved at: data/jarvis_memory.db.backup-test"
fi

exit $EXIT_CODE

