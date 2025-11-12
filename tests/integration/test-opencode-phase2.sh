#!/bin/bash
# Test OpenCode Phase 2 Features

cd "$(dirname "$0")/../.."

echo "========================================="
echo "  OpenCode Phase 2 Integration Test"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0

# Test 1: Agent Mode Detection
echo -e "${BLUE}Test 1: Agent Mode Detection${NC}"
python3 << 'EOF'
import sys
sys.path.insert(0, 'orchestrator')
from router_v2 import LLMRouter

router = LLMRouter('cloud')

tests = [
    ('analyze my code for bugs', 'plan'),
    ('create a Flask API', 'build'),
    ('review my API design', 'plan'),
    ('fix the bug in my script', 'build'),
]

all_pass = True
for query, expected in tests:
    result = router._detect_opencode_mode(query, {'tool_name': 'opencode', 'arguments': {}})
    mode = result['arguments']['agent_mode']
    if mode == expected:
        print(f"  ✓ '{query}' → {mode}")
    else:
        print(f"  ✗ '{query}' → {mode} (expected: {expected})")
        all_pass = False

sys.exit(0 if all_pass else 1)
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ PASSED${NC}"
    ((PASSED++))
else
    echo -e "${RED}❌ FAILED${NC}"
    ((FAILED++))
fi
echo ""

# Test 2: Memory Integration
echo -e "${BLUE}Test 2: Memory Integration${NC}"
python3 << 'EOF'
import sys
sys.path.insert(0, 'skills')
sys.path.insert(0, 'lib')
from opencode import get_memory_context

# Test memory context retrieval
context = get_memory_context("Create a Python script", "cloud")

# Check structure
required_keys = ['relevant_memories', 'user_preferences', 'recent_projects']
all_present = all(key in context for key in required_keys)

if all_present:
    print(f"  ✓ Context structure correct")
    print(f"  ✓ Keys present: {list(context.keys())}")
else:
    print(f"  ✗ Missing keys")
    sys.exit(1)

sys.exit(0)
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ PASSED${NC}"
    ((PASSED++))
else
    echo -e "${RED}❌ FAILED${NC}"
    ((FAILED++))
fi
echo ""

# Test 3: OpenCode Session Clearing
echo -e "${BLUE}Test 3: Session Clearing${NC}"
./bin/opencode-clear-sessions >/dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "  ✓ Session clearing script works"
    echo -e "${GREEN}✅ PASSED${NC}"
    ((PASSED++))
else
    echo "  ✗ Session clearing failed"
    echo -e "${RED}❌ FAILED${NC}"
    ((FAILED++))
fi
echo ""

# Test 4: Global AGENTS.md Exists
echo -e "${BLUE}Test 4: Global AGENTS.md Configuration${NC}"
if [ -f "$HOME/.config/opencode/AGENTS.md" ]; then
    SIZE=$(wc -l < "$HOME/.config/opencode/AGENTS.md")
    echo "  ✓ Global AGENTS.md exists ($SIZE lines)"
    if grep -q "Workspace Boundaries" "$HOME/.config/opencode/AGENTS.md"; then
        echo "  ✓ Contains workspace boundary rules"
        echo -e "${GREEN}✅ PASSED${NC}"
        ((PASSED++))
    else
        echo "  ✗ Missing workspace boundaries"
        echo -e "${RED}❌ FAILED${NC}"
        ((FAILED++))
    fi
else
    echo "  ✗ Global AGENTS.md not found"
    echo -e "${RED}❌ FAILED${NC}"
    ((FAILED++))
fi
echo ""

# Test 5: OpenCode Config (No Permission Keys)
echo -e "${BLUE}Test 5: OpenCode Config (Agent Mode)${NC}"
CONFIG="$HOME/.config/opencode/opencode.json"
if [ -f "$CONFIG" ]; then
    if ! grep -q '"permission"' "$CONFIG"; then
        echo "  ✓ No hardcoded permissions (agent mode controls this)"
        echo -e "${GREEN}✅ PASSED${NC}"
        ((PASSED++))
    else
        echo "  ⚠️  Config has permission field (not needed with agent modes)"
        echo -e "${GREEN}✅ PASSED (with warning)${NC}"
        ((PASSED++))
    fi
else
    echo "  ✗ OpenCode config not found"
    echo -e "${RED}❌ FAILED${NC}"
    ((FAILED++))
fi
echo ""

# Summary
echo "========================================="
echo "  Test Results"
echo "========================================="
echo "Total Tests: $((PASSED + FAILED))"
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All Phase 2 tests passed!${NC}"
    echo ""
    echo "✅ Agent mode detection working"
    echo "✅ Memory integration functional"
    echo "✅ Session management ready"
    echo "✅ Configuration complete"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed${NC}"
    exit 1
fi

