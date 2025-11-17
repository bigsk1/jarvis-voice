#!/bin/bash
# Comprehensive API endpoint tests
# Tests all endpoints: alerts, reminders, voice, health

API_URL="http://localhost:8880"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Jarvis Proactive Assistant - API Tests                ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check if server is running
if ! curl -s "$API_URL/api/health" > /dev/null 2>&1; then
    echo -e "${RED}❌ API server not running on port 8880${NC}"
    echo ""
    echo "Start the server first:"
    echo "  ./bin/jarvis-api         # Cloud mode"
    echo "  ./bin/jarvis-api --local # Local mode"
    exit 1
fi

echo -e "${GREEN}✅ API server is running${NC}"
echo ""

PASSED=0
FAILED=0

# Test 1: Health Check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 1: Health Check${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s "$API_URL/api/health")
if echo "$RESPONSE" | jq -e '.status == "ok"' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: $RESPONSE"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 2: System Status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 2: System Status${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s "$API_URL/api/status")
if echo "$RESPONSE" | jq -e '.status == "running"' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: $RESPONSE"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 3: Create Low-Priority Alert (no TTS)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 3: Create Low-Priority Alert (no TTS)${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s -X POST "$API_URL/api/alerts" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Low Priority Alert",
    "description": "This should NOT speak",
    "severity": "low",
    "source": "test_script"
  }')

if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    ALERT_ID_1=$(echo "$RESPONSE" | jq -r '.alert_id')
    echo "Alert ID: $ALERT_ID_1"
    echo "Response: $(echo $RESPONSE | jq -c)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 4: Create High-Priority Alert (WITH TTS)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 4: Create High-Priority Alert (WITH TTS)${NC}"
echo -e "${YELLOW}⚠️  This should trigger Jarvis to speak!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s -X POST "$API_URL/api/alerts" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "High Priority Test Alert",
    "description": "This SHOULD speak via TTS",
    "severity": "high",
    "source": "test_script",
    "metadata": {"test": true}
  }')

if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    ALERT_ID_2=$(echo "$RESPONSE" | jq -r '.alert_id')
    echo "Alert ID: $ALERT_ID_2"
    echo "Response: $(echo $RESPONSE | jq -c)"
    echo -e "${YELLOW}🔊 Did you hear Jarvis speak?${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""
sleep 2

# Test 5: List All Alerts
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 5: List All Alerts${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s "$API_URL/api/alerts")
if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    COUNT=$(echo "$RESPONSE" | jq -r '.alerts | length')
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Found $COUNT alerts"
    echo "$RESPONSE" | jq -c '.alerts[] | {id, title, severity, status}'
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 6: List Pending Alerts Only
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 6: List Pending Alerts Only${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s "$API_URL/api/alerts?status=pending")
if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    COUNT=$(echo "$RESPONSE" | jq -r '.alerts | length')
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Found $COUNT pending alerts"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 7: Get Specific Alert
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 7: Get Specific Alert${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s "$API_URL/api/alerts/$ALERT_ID_1")
if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "$RESPONSE" | jq -c '.alert | {id, title, status}'
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 8: Acknowledge Alert
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 8: Acknowledge Alert${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s -X PUT "$API_URL/api/alerts/$ALERT_ID_1/acknowledge")
if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: $(echo $RESPONSE | jq -c)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 9: Acknowledge All Pending Alerts
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 9: Acknowledge All Pending Alerts${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s -X POST "$API_URL/api/alerts/acknowledge-all")
if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: $(echo $RESPONSE | jq -c)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 10: Create Reminder (1 minute from now)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 10: Create Reminder (1 minute from now)${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Calculate time 1 minute from now in ISO 8601 format
TRIGGER_TIME=$(date -u -d '+1 minute' '+%Y-%m-%dT%H:%M:%S')

RESPONSE=$(curl -s -X POST "$API_URL/api/reminders" \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Test Reminder\",
    \"description\": \"This reminder should trigger in 1 minute\",
    \"trigger_time\": \"${TRIGGER_TIME}\"
  }")

if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    REMINDER_ID=$(echo "$RESPONSE" | jq -r '.reminder_id')
    echo "Reminder ID: $REMINDER_ID"
    echo "Trigger Time: $TRIGGER_TIME"
    echo -e "${YELLOW}⏰ Reminder set for 1 minute from now${NC}"
    echo -e "${YELLOW}   (Manual trigger needed - background daemon not implemented yet)${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 11: List Reminders
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 11: List Reminders${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s "$API_URL/api/reminders")
if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    COUNT=$(echo "$RESPONSE" | jq -r '.reminders | length')
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Found $COUNT reminders"
    echo "$RESPONSE" | jq -c '.reminders[] | {id, title, trigger_time, status}'
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 12: Manual TTS Test
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 12: Manual TTS Test${NC}"
echo -e "${YELLOW}⚠️  This should trigger Jarvis to speak!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s -X POST "$API_URL/api/voice/speak" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "API test complete! All endpoints working!",
    "mode": "cloud"
  }')

if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: $(echo $RESPONSE | jq -c)"
    echo -e "${YELLOW}🔊 Did you hear Jarvis speak?${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 13: Create Alert with Auto-Resolve URL
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 13: Create Alert with Auto-Resolve URL${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s -X POST "$API_URL/api/alerts" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Server Down (example.com)",
    "description": "Testing auto-resolve functionality",
    "severity": "medium",
    "source": "test_script",
    "auto_resolve_url": "https://example.com",
    "auto_resolve_check_interval": 60
  }')

if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    ALERT_ID_3=$(echo "$RESPONSE" | jq -r '.alert_id')
    echo "Alert ID: $ALERT_ID_3"
    echo "Response: $(echo $RESPONSE | jq -c)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test 14: Manual Auto-Resolve Check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test 14: Manual Auto-Resolve Check${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
RESPONSE=$(curl -s -X POST "$API_URL/api/alerts/$ALERT_ID_3/check")
if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    echo -e "${GREEN}✅ PASSED${NC}"
    echo "Response: $(echo $RESPONSE | jq -c)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}❌ FAILED${NC}"
    echo "Response: $RESPONSE"
    FAILED=$((FAILED + 1))
fi
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}Test Summary${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
TOTAL=$((PASSED + FAILED))
echo -e "Total Tests: ${BLUE}$TOTAL${NC}"
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed${NC}"
    exit 1
fi

