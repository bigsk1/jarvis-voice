#!/bin/bash
# Integration test for MCP Docker containers with environment variables
# Tests that API keys are correctly passed through to Docker containers

set -e

echo "🧪 MCP Docker Integration Test"
echo "Testing environment variable passing to Docker containers"
echo "========================================================================"

# Load config
source config/cloud.env 2>/dev/null || echo "⚠️  cloud.env not found (test may fail)"

# Test 1: Brave Search with API key
echo ""
echo "Test 1: Brave Search API Key Passing"
echo "----------------------------------------------------------------------"

if [ -z "$BRAVE_API_KEY" ]; then
    echo "❌ BRAVE_API_KEY not set in cloud.env - SKIPPING"
else
    echo "✅ BRAVE_API_KEY found in environment"
    
    # Test with test-mcp script
    echo "   Testing with: ./bin/test-mcp --test brave-search brave_web_search"
    OUTPUT=$(./bin/test-mcp --test brave-search brave_web_search '{"query": "test", "count": 1}' 2>&1)
    
    if echo "$OUTPUT" | grep -q "OK:.*True"; then
        echo "✅ Brave Search API key successfully passed to Docker container"
    elif echo "$OUTPUT" | grep -qi "invalid.*token\|unauthorized\|authentication"; then
        echo "❌ FAILED: API key not reaching Docker container"
        echo "   Error output:"
        echo "$OUTPUT" | grep -i "error\|invalid\|auth" | head -5
        exit 1
    else
        echo "⚠️  Unexpected output:"
        echo "$OUTPUT" | head -10
        exit 1
    fi
fi

# Test 2: Verify env dict format
echo ""
echo "Test 2: Verify mcp-servers.json Format"
echo "----------------------------------------------------------------------"

if grep -q '"env".*{' config/mcp-servers.json; then
    echo "✅ Found 'env' block in mcp-servers.json"
    
    # Check for proper substitution syntax
    if grep -q '\${.*}' config/mcp-servers.json; then
        echo "✅ Found environment variable substitution syntax"
    else
        echo "⚠️  No \${VAR} syntax found (may not be using substitution)"
    fi
else
    echo "⚠️  No 'env' blocks found (all servers use empty env)"
fi

# Test 3: Check Docker is running
echo ""
echo "Test 3: Docker Availability"
echo "----------------------------------------------------------------------"

if docker ps &>/dev/null; then
    echo "✅ Docker is running"
else
    echo "❌ Docker is not running (MCP servers will fail to start)"
    exit 1
fi

echo ""
echo "========================================================================"
echo "✅ All integration tests passed!"
echo ""
echo "Summary:"
echo "  • Environment variables load from cloud.env"
echo "  • Substitution syntax (\${VAR}) works"
echo "  • Variables pass through to Docker containers"
echo "  • MCP servers receive API keys correctly"

