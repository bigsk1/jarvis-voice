#!/bin/bash
# Comprehensive Thinking Mode Tests
# Tests all scenarios: cloud/local, with/without thinking, various models

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     THINKING MODE COMPREHENSIVE TEST SUITE                ║${NC}"
echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo ""

# Track results
TOTAL=0
PASSED=0
FAILED=0

run_test() {
    local name="$1"
    local mode="$2"
    local query="$3"
    local thinking_flag="$4"
    local expect_thinking="$5"
    
    TOTAL=$((TOTAL + 1))
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}Test $TOTAL: $name${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "Mode: $mode | Query: \"$query\""
    echo -e "Thinking flag: $thinking_flag | Expect thinking: $expect_thinking"
    echo ""
    
    # Build command
    cmd="./orchestrator/orchestrator_v2.py $mode \"$query\""
    if [ "$thinking_flag" = "true" ]; then
        cmd="$cmd --debug-thinking"
    fi
    
    echo -e "${CYAN}Running: $cmd${NC}"
    echo ""
    
    # Run and capture output
    if output=$($cmd 2>&1); then
        # Check if thinking was displayed
        if echo "$output" | grep -q "🧠 LLM Thinking:"; then
            thinking_found="true"
        else
            thinking_found="false"
        fi
        
        # Validate expectations
        if [ "$expect_thinking" = "$thinking_found" ]; then
            echo -e "${GREEN}✅ PASS${NC}"
            PASSED=$((PASSED + 1))
        else
            echo -e "${RED}❌ FAIL - Expected thinking=$expect_thinking, got=$thinking_found${NC}"
            FAILED=$((FAILED + 1))
        fi
        
        # Show abbreviated output
        echo ""
        echo -e "${CYAN}Output preview:${NC}"
        echo "$output" | head -20
        echo "..."
        echo "$output" | tail -10
    else
        echo -e "${RED}❌ FAIL - Command failed${NC}"
        echo "$output"
        FAILED=$((FAILED + 1))
    fi
}

echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  SECTION 1: Cloud Mode Tests (Anthropic Sonnet 4.5)${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"

run_test \
    "Cloud WITHOUT thinking flag (should not show thinking)" \
    "cloud" \
    "What time is it?" \
    "false" \
    "false"

run_test \
    "Cloud WITH thinking flag (should show thinking)" \
    "cloud" \
    "Should I save the Bitcoin price?" \
    "true" \
    "true"

run_test \
    "Cloud WITH thinking - Grey area decision" \
    "cloud" \
    "I'm really excited about the new Predator movie and don't want to miss it. Search for when it comes out." \
    "true" \
    "true"

echo ""
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  SECTION 2: Local Mode Tests (Check current model)${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"

# Check which local model is active
LOCAL_MODEL=$(grep "^OLLAMA_MODEL=" config/local.env | cut -d'=' -f2 | tr -d '"')
echo -e "${CYAN}Current local model: $LOCAL_MODEL${NC}"
echo ""

if [[ "$LOCAL_MODEL" == *"deepseek-r1"* ]]; then
    echo -e "${GREEN}DeepSeek R1 detected - should support thinking${NC}"
    EXPECT_LOCAL_THINKING="true"
else
    echo -e "${YELLOW}Non-thinking model detected - should gracefully skip${NC}"
    EXPECT_LOCAL_THINKING="false"
fi
echo ""

run_test \
    "Local WITHOUT thinking flag" \
    "local" \
    "What time is it?" \
    "false" \
    "false"

run_test \
    "Local WITH thinking flag" \
    "local" \
    "What is the current time in Tokyo?" \
    "true" \
    "$EXPECT_LOCAL_THINKING"

echo ""
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  SECTION 3: Thinking Logs Verification${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"

TODAY=$(date +%Y-%m-%d)
LOG_FILE="logs/thinking/${TODAY}_decisions.jsonl"

if [ -f "$LOG_FILE" ]; then
    ENTRY_COUNT=$(wc -l < "$LOG_FILE")
    echo -e "${GREEN}✅ Thinking log exists: $LOG_FILE${NC}"
    echo -e "${CYAN}   Entries: $ENTRY_COUNT${NC}"
    echo ""
    echo -e "${CYAN}Latest entry:${NC}"
    tail -1 "$LOG_FILE" | jq '.' 2>/dev/null || tail -1 "$LOG_FILE"
else
    echo -e "${YELLOW}⚠️  No thinking logs found (expected if thinking not enabled)${NC}"
fi

echo ""
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  TEST SUMMARY${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "Total tests:  $TOTAL"
echo -e "${GREEN}Passed:       $PASSED${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed:       $FAILED${NC}"
else
    echo -e "Failed:       $FAILED"
fi
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              ALL TESTS PASSED! 🎉                          ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    exit 0
else
    echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║              SOME TESTS FAILED                             ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    exit 1
fi

