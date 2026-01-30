#!/bin/bash
# Real-world complex memory test scenarios
# Not "I love pizza" baby stuff - actual challenging queries

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         Real-World Memory Intelligence Test                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate

# Backup and clean
if [ -f data/jarvis_memory.db ]; then
    cp data/jarvis_memory.db data/jarvis_memory.db.backup-realworld
    rm data/jarvis_memory.db
fi
./bin/setup-memory-db.sh > /dev/null 2>&1

# CRITICAL: Sync tool definitions for Tool RAG
echo "🔧 Syncing tool definitions..."
./bin/sync_tools.py cloud > /dev/null 2>&1
echo "✅ Tool RAG ready"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SCENARIO 1: Complex Context - Multiple Related Facts"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Building context... (natural conversation, not obvious 'remember this')"
./orchestrator/orchestrator_v2.py cloud "I'm working on a Flask API that handles user authentication. It's running on port 8091 and uses JWT tokens. The database is PostgreSQL on localhost:5432" > /tmp/rw1.log 2>&1
sleep 1
./orchestrator/orchestrator_v2.py cloud "By the way, the admin panel is at /admin and requires the secret key 'dev-secret-123' for local testing" > /tmp/rw2.log 2>&1
sleep 1
./orchestrator/orchestrator_v2.py cloud "Oh and I deployed this to my VPS at 192.168.1.228" > /tmp/rw3.log 2>&1
sleep 2

echo "Context built. Now testing recall with complex queries..."
echo ""

# Complex query 1: Indirect reference
echo "Q1: 'How do I access the administrative interface?'"
./orchestrator/orchestrator_v2.py cloud "How do I access the administrative interface?" > /tmp/rw4.log 2>&1
if grep -iq "admin" /tmp/rw4.log && grep -iq "8091\|secret" /tmp/rw4.log; then
    echo "   ✅ PASS - Found admin panel info (semantic understanding: 'administrative interface' = 'admin panel')"
else
    echo "   ❌ FAIL - Didn't connect 'administrative interface' to 'admin panel'"
    cat /tmp/rw4.log | grep -i "speech"
fi
echo ""

# Complex query 2: Relationship inference
echo "Q2: 'What's the IP address where my authentication system is deployed?'"
./orchestrator/orchestrator_v2.py cloud "What's the IP address where my authentication system is deployed?" > /tmp/rw5.log 2>&1
if grep -q "192.168.1.228" /tmp/rw5.log; then
    echo "   ✅ PASS - Connected 'authentication system' to 'Flask API' to 'VPS IP'"
else
    echo "   ❌ FAIL - Didn't infer relationship between concepts"
    cat /tmp/rw5.log | grep -i "speech"
fi
echo ""

# Complex query 3: Technical detail retrieval
echo "Q3: 'Which database am I using for user management?'"
./orchestrator/orchestrator_v2.py cloud "Which database am I using for user management?" > /tmp/rw6.log 2>&1
if grep -iq "postgres" /tmp/rw6.log; then
    echo "   ✅ PASS - Connected 'user management' to 'authentication' to 'PostgreSQL'"
else
    echo "   ❌ FAIL - Didn't infer technical details"
    cat /tmp/rw6.log | grep -i "speech"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SCENARIO 2: Temporal & Conditional Context"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Building temporal context..."
./orchestrator/orchestrator_v2.py cloud "I tried deploying to Heroku but ran into SSL certificate issues. Switched to DigitalOcean and it worked perfectly with Nginx" > /tmp/rw7.log 2>&1
sleep 1
./orchestrator/orchestrator_v2.py cloud "For monitoring, I set up Grafana on port 3000 and Prometheus on 9090. Grafana dashboard URL is https://monitoring.myapp.com" > /tmp/rw8.log 2>&1
sleep 2

echo ""
echo "Q4: 'What deployment platform am I currently using?'"
./orchestrator/orchestrator_v2.py cloud "What deployment platform am I currently using?" > /tmp/rw9.log 2>&1
if grep -iq "digitalocean\|digital ocean" /tmp/rw9.log && ! grep -iq "heroku" /tmp/rw9.log; then
    echo "   ✅ PASS - Understood 'currently' = DigitalOcean (not Heroku)"
else
    echo "   ⚠️  PARTIAL - Found deployment info but may have mentioned old platform"
    cat /tmp/rw9.log | grep -i "speech"
fi
echo ""

echo "Q5: 'Where can I see the metrics dashboard?'"
./orchestrator/orchestrator_v2.py cloud "Where can I see the metrics dashboard?" > /tmp/rw10.log 2>&1
if grep -q "monitoring.myapp.com\|grafana" /tmp/rw10.log; then
    echo "   ✅ PASS - Connected 'metrics dashboard' to 'Grafana'"
else
    echo "   ❌ FAIL - Didn't understand 'metrics dashboard' = Grafana"
    cat /tmp/rw10.log | grep -i "speech"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SCENARIO 3: Ambiguous / Multi-Entity Queries"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Building multi-entity context..."
./orchestrator/orchestrator_v2.py cloud "I have three servers: dev server on 192.168.1.10, staging on 192.168.1.20, and production on 192.168.1.30. Each runs different services" > /tmp/rw11.log 2>&1
sleep 1
./orchestrator/orchestrator_v2.py cloud "Dev has the experimental AI features, staging has the payment gateway test, and production has the live customer data" > /tmp/rw12.log 2>&1
sleep 2

echo ""
echo "Q6: 'Which server should I test the payment integration on?'"
./orchestrator/orchestrator_v2.py cloud "Which server should I test the payment integration on?" > /tmp/rw13.log 2>&1
if grep -q "staging\|192.168.1.20" /tmp/rw13.log; then
    echo "   ✅ PASS - Correctly identified staging server for payment testing"
else
    echo "   ❌ FAIL - Didn't connect payment testing to staging"
    cat /tmp/rw13.log | grep -i "speech"
fi
echo ""

echo "Q7: 'What's on the server at .30?'"
./orchestrator/orchestrator_v2.py cloud "What's on the server at .30?" > /tmp/rw14.log 2>&1
if grep -iq "production\|customer data" /tmp/rw14.log; then
    echo "   ✅ PASS - Understood '.30' = '192.168.1.30' = production"
else
    echo "   ❌ FAIL - Didn't infer IP shorthand"
    cat /tmp/rw14.log | grep -i "speech"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SCENARIO 4: Problem-Solution Memory (Should Auto-Save)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "User describes a problem and solution (should auto-save as technical knowledge)..."
./orchestrator/orchestrator_v2.py cloud "I was getting 'CORS blocked' errors in the browser. Fixed it by adding 'Access-Control-Allow-Origin: *' to the Nginx config at /etc/nginx/sites-available/myapp" > /tmp/rw15.log 2>&1
sleep 2

echo ""
echo "Q8: 'How did I fix the cross-origin issue before?'"
./orchestrator/orchestrator_v2.py cloud "How did I fix the cross-origin issue before?" > /tmp/rw16.log 2>&1
if grep -iq "cors\|nginx\|access-control" /tmp/rw16.log; then
    echo "   ✅ PASS - Recalled technical solution (cross-origin = CORS)"
else
    echo "   ❌ FAIL - Didn't save or recall technical solution"
    cat /tmp/rw16.log | grep -i "speech"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SCENARIO 5: Should NOT Save (Noise Filtering)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Testing if LLM correctly avoids saving ephemeral/noise data..."
echo ""

echo "Q9: 'What's the current Bitcoin price?' (should not save)"
BEFORE_COUNT=$(sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM knowledge_base")
./orchestrator/orchestrator_v2.py cloud "What's the current Bitcoin price?" > /tmp/rw17.log 2>&1
AFTER_COUNT=$(sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM knowledge_base")
if [ "$BEFORE_COUNT" -eq "$AFTER_COUNT" ]; then
    echo "   ✅ PASS - Did NOT save ephemeral price data"
else
    echo "   ❌ FAIL - Incorrectly saved ephemeral data"
fi
echo ""

echo "Q10: 'Test webhook to httpbin.org' (should not save test URLs)"
BEFORE_COUNT=$(sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM knowledge_base")
./orchestrator/orchestrator_v2.py cloud "Send test webhook to https://httpbin.org/post with data test" > /tmp/rw18.log 2>&1
sleep 1
AFTER_COUNT=$(sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM knowledge_base")
if [ "$BEFORE_COUNT" -eq "$AFTER_COUNT" ]; then
    echo "   ✅ PASS - Did NOT save temporary test URL"
else
    echo "   ⚠️  WARNING - May have saved test URL (check if important)"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "ANALYSIS: What Was Actually Saved?"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Memories saved during test:"
sqlite3 data/jarvis_memory.db "SELECT id, category, key, value, importance FROM knowledge_base ORDER BY id" | column -t -s "|"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TOOL USAGE ANALYSIS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "Which tools were used for memory operations?"
grep -h "semantic_recall\|search_memory\|recall" logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '.tool_name' | sort | uniq -c | sort -rn || echo "No memory tool usage found"
echo ""

echo "Auto-saves triggered:"
grep -h "remember" logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq -r '{tool: .tool_name, args: .tool_args}' | head -10 || echo "No auto-saves"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "FINAL VERDICT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "This test checks:"
echo "  ✓ Semantic understanding (not just keyword matching)"
echo "  ✓ Relationship inference across multiple facts"
echo "  ✓ Auto-save intelligence (save important, skip noise)"
echo "  ✓ Temporal context ('currently' vs past)"
echo "  ✓ Ambiguous query resolution"
echo ""
echo "Review the results above to assess real-world readiness."
echo ""
echo "Logs: /tmp/rw*.log"
echo "Database: data/jarvis_memory.db"
echo "Backup: data/jarvis_memory.db.backup-realworld"
echo ""

