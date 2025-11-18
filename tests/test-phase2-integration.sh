#!/bin/bash
# Phase 2 Integration Test
# Tests intel management tool and validates service scripts exist

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Jarvis Phase 2 Integration Test                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

TESTS_PASSED=0
TESTS_FAILED=0

# Test 1: Check intel management tool exists
echo -e "${BLUE}Test 1: Intel Management Tool${NC}"
if [ -f "skills/manage_intel.py" ] && [ -f "skills/manage_intel.tool.json" ]; then
    echo -e "${GREEN}  ✅ PASS: manage_intel tool files exist${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}  ❌ FAIL: manage_intel tool files missing${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 2: Check service daemons exist
echo -e "${BLUE}Test 2: Background Service Daemons${NC}"
SERVICES_OK=true

if [ ! -f "services/follow_up_daemon.py" ]; then
    echo -e "${RED}  ❌ FAIL: follow_up_daemon.py missing${NC}"
    SERVICES_OK=false
fi

if [ ! -f "services/self_healing_daemon.py" ]; then
    echo -e "${RED}  ❌ FAIL: self_healing_daemon.py missing${NC}"
    SERVICES_OK=false
fi

if [ ! -f "services/reminder_scheduler.py" ]; then
    echo -e "${RED}  ❌ FAIL: reminder_scheduler.py missing${NC}"
    SERVICES_OK=false
fi

if [ "$SERVICES_OK" = true ]; then
    echo -e "${GREEN}  ✅ PASS: All service daemons exist${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 3: Check jarvis-services startup script
echo -e "${BLUE}Test 3: Service Startup Script${NC}"
if [ -f "bin/jarvis-services" ] && [ -x "bin/jarvis-services" ]; then
    echo -e "${GREEN}  ✅ PASS: jarvis-services script exists and is executable${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}  ❌ FAIL: jarvis-services script missing or not executable${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 4: Test intel management - create
echo -e "${BLUE}Test 4: Intel Management - Create File${NC}"
TEST_FILE="test-phase2-$(date +%s).md"
CREATE_RESULT=$(echo "{\"action\": \"create\", \"path\": \"$TEST_FILE\", \"content\": \"# Test\nThis is a test file for Phase 2\", \"auto_ingest\": false}" | python3 skills/manage_intel.py 2>&1)

if echo "$CREATE_RESULT" | grep -q '"ok": true'; then
    echo -e "${GREEN}  ✅ PASS: Created test intel file${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}  ❌ FAIL: Failed to create intel file${NC}"
    echo "$CREATE_RESULT"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 5: Test intel management - read
echo -e "${BLUE}Test 5: Intel Management - Read File${NC}"
READ_RESULT=$(echo "{\"action\": \"read\", \"path\": \"$TEST_FILE\"}" | python3 skills/manage_intel.py 2>&1)

if echo "$READ_RESULT" | grep -q '"ok": true' && echo "$READ_RESULT" | grep -q "Phase 2"; then
    echo -e "${GREEN}  ✅ PASS: Read test intel file${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}  ❌ FAIL: Failed to read intel file${NC}"
    echo "$READ_RESULT"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 6: Test intel management - update
echo -e "${BLUE}Test 6: Intel Management - Update File${NC}"
UPDATE_RESULT=$(echo "{\"action\": \"update\", \"path\": \"$TEST_FILE\", \"content\": \"# Test Updated\nThis is an updated test file\", \"auto_ingest\": false}" | python3 skills/manage_intel.py 2>&1)

if echo "$UPDATE_RESULT" | grep -q '"ok": true'; then
    echo -e "${GREEN}  ✅ PASS: Updated test intel file${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}  ❌ FAIL: Failed to update intel file${NC}"
    echo "$UPDATE_RESULT"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 7: Test intel management - list
echo -e "${BLUE}Test 7: Intel Management - List Files${NC}"
LIST_RESULT=$(echo '{"action": "list"}' | python3 skills/manage_intel.py 2>&1)

if echo "$LIST_RESULT" | grep -q '"ok": true'; then
    echo -e "${GREEN}  ✅ PASS: Listed intel files${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}  ❌ FAIL: Failed to list intel files${NC}"
    echo "$LIST_RESULT"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 8: Test intel management - delete
echo -e "${BLUE}Test 8: Intel Management - Delete File${NC}"
DELETE_RESULT=$(echo "{\"action\": \"delete\", \"path\": \"$TEST_FILE\"}" | python3 skills/manage_intel.py 2>&1)

if echo "$DELETE_RESULT" | grep -q '"ok": true'; then
    echo -e "${GREEN}  ✅ PASS: Deleted test intel file${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}  ❌ FAIL: Failed to delete intel file${NC}"
    echo "$DELETE_RESULT"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Test 9: Check alert voice control tools
echo -e "${BLUE}Test 9: Alert Voice Control Tools${NC}"
ALERT_TOOLS_OK=true

if [ ! -f "skills/list_alerts.py" ]; then
    echo -e "${RED}  ❌ FAIL: list_alerts.py missing${NC}"
    ALERT_TOOLS_OK=false
fi

if [ ! -f "skills/acknowledge_alerts.py" ]; then
    echo -e "${RED}  ❌ FAIL: acknowledge_alerts.py missing${NC}"
    ALERT_TOOLS_OK=false
fi

if [ "$ALERT_TOOLS_OK" = true ]; then
    echo -e "${GREEN}  ✅ PASS: Alert voice control tools exist${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Test Results:${NC}"
echo -e "  ${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "  ${RED}Failed: $TESTS_FAILED${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ALL TESTS PASSED - Phase 2 Integration Successful!${NC}"
    echo ""
    echo -e "${BLUE}Next Steps:${NC}"
    echo "  1. Start API server: ./bin/jarvis-api"
    echo "  2. Start services: ./bin/jarvis-services"
    echo "  3. Start voice mode: ./jarvis"
    echo ""
    echo "  All three can run simultaneously!"
    echo ""
    exit 0
else
    echo -e "${RED}❌ SOME TESTS FAILED - Please review errors above${NC}"
    echo ""
    exit 1
fi

