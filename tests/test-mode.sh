#!/bin/bash
# Quick test to verify cloud vs local mode

echo "Testing API Mode Selection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test cloud mode
echo "1. Testing CLOUD mode (should use say.sh + alloy voice)"
echo "   Start: ./bin/jarvis-api"
echo ""
curl -s http://localhost:8880/api/status | jq '{mode, database, env_mode, llm_provider}'
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Stop the server (Ctrl+C) and restart with:"
echo "   ./bin/jarvis-api --local"
echo ""
echo "Then run this again to verify local mode"

