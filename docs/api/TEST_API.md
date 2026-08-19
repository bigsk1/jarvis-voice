# 🧪 API Testing Guide

## Quick Test Commands

### 1. Start API Server

**Cloud Mode:**
```bash
./bin/jarvis-api
```

**Local Mode (Offline):**
```bash
./bin/jarvis-api --local
```

### 2. Run Comprehensive Tests

```bash
./tests/test-api-endpoints.sh
```

**This tests:**
- ✅ Health check
- ✅ System status
- ✅ Create alerts (low, high, medium severity)
- ✅ List alerts (all, pending, by severity)
- ✅ Get specific alert
- ✅ Acknowledge alerts (single and bulk)
- ✅ Create reminders
- ✅ List reminders
- ✅ Manual TTS
- ✅ Auto-resolve functionality

### 3. Manual Tests

**Create a test alert:**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Alert",
    "description": "Testing webhooks",
    "severity": "high",
    "source": "test"
  }'
```

**List all alerts:**
```bash
curl http://localhost:8880/api/alerts | jq
```

**Acknowledge alert #1:**
```bash
curl -X PUT http://localhost:8880/api/alerts/1/acknowledge
```

**Clear all pending alerts:**
```bash
curl -X POST http://localhost:8880/api/alerts/acknowledge-all
```

**Create reminder:**
```bash
curl -X POST http://localhost:8880/api/reminders \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Check something",
    "description": "Reminder description",
    "trigger_time": "2025-11-17T06:31:00"
  }'
```

**Manual TTS test:**
```bash
curl -X POST http://localhost:8880/api/voice/speak \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Testing text to speech!",
    "mode": "cloud"
  }'
```

### 4. Test Mode Isolation

**Scenario**: Create an alert in cloud mode, switch to local mode, and verify it
remains cloud-local.

**Steps:**
```bash
# 1. Start cloud API
./bin/jarvis-api

# 2. Create alert
curl -X POST http://localhost:8880/api/alerts \
  -d '{"title": "Mode Isolation Test", "source": "test"}' \
  -H "Content-Type: application/json"

# 3. Stop cloud API (Ctrl+C)

# 4. Start local API
./bin/jarvis-api --local

# 5. List alerts (should not include "Mode Isolation Test")
curl http://localhost:8880/api/alerts | jq '.alerts[] | {title, source}'
```

**Expected:** The cloud alert is absent from the local database. Restart cloud
mode to list or manage it.

### 5. Test Reminder (Automated)

The `reminder_scheduler` daemon (started by `bin/jarvis-services`) processes due reminders automatically.

```bash
# 1. Create reminder for 1 minute from now
TRIGGER_TIME=$(date -u -d '+1 minute' '+%Y-%m-%dT%H:%M:%S')
curl -X POST http://localhost:8880/api/reminders \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Test Reminder\",
    \"description\": \"Should trigger in 1 minute\",
    \"trigger_time\": \"${TRIGGER_TIME}\"
  }"

# 2. Wait ~1 minute, then verify the daemon fired it
curl http://localhost:8880/api/reminders | jq '.reminders[] | select(.status == "triggered")'

# 3. Optional: check daemon log
tail -20 logs/reminder_scheduler.log
```

### 6. Test Different Severities

**Low (no TTS):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Low Priority", "severity": "low", "source": "test"}'
```

**Medium (no TTS):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Medium Priority", "severity": "medium", "source": "test"}'
```

**High (WITH TTS 🔊):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "High Priority", "severity": "high", "source": "test"}'
```

**Critical (WITH TTS 🔊):**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "CRITICAL ALERT", "severity": "critical", "source": "test"}'
```

### 7. Test Auto-Resolve

```bash
# Create alert with auto-resolve URL
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Server Down (example.com)",
    "severity": "high",
    "source": "test",
    "auto_resolve_url": "https://example.com"
  }'

# Get alert ID from response, then manually check
curl -X POST http://localhost:8880/api/alerts/1/check

# If example.com is reachable (200 OK), alert auto-resolves
```

### 8. Test Interactive Docs

Visit: http://localhost:8880/docs

- Try each endpoint interactively
- See request/response schemas
- Test directly in browser

### 9. Test Query Filters

**By status:**
```bash
curl "http://localhost:8880/api/alerts?status=pending" | jq
curl "http://localhost:8880/api/alerts?status=acknowledged" | jq
```

**By severity:**
```bash
curl "http://localhost:8880/api/alerts?severity=high" | jq
curl "http://localhost:8880/api/alerts?severity=critical" | jq
```

**By source:**
```bash
curl "http://localhost:8880/api/alerts?source=uptime_kuma" | jq
curl "http://localhost:8880/api/alerts?source=test" | jq
```

**Combined:**
```bash
curl "http://localhost:8880/api/alerts?status=pending&severity=high" | jq
```

### 10. Test Error Handling

**Invalid severity:**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "severity": "invalid", "source": "test"}'
# Should return 422 validation error
```

**Missing required field:**
```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"description": "Missing title"}'
# Should return 422 validation error
```

**Non-existent alert:**
```bash
curl http://localhost:8880/api/alerts/99999
# Should return 404
```

## Expected Behavior

### TTS Triggers
- ✅ **High** severity → Jarvis speaks immediately
- ✅ **Critical** severity → Jarvis speaks immediately
- ❌ **Medium** severity → No TTS (silent)
- ❌ **Low** severity → No TTS (silent)

### Database Storage
- ✅ All alerts stored in database
- ✅ All reminders stored in database
- ✅ Alerts stay local to their cloud or local mode database
- ✅ Reminders stay local to their cloud or local mode database

### Auto-Resolve
- ✅ Checks configured URL (HTTP GET)
- ✅ 2xx/3xx response → Auto-resolves
- ✅ 4xx/5xx or timeout → Stays active

## Troubleshooting

**Server not responding:**
```bash
# Check if running
lsof -i :8880

# Check logs (if background)
tail -f logs/api.log
```

**TTS not working:**
```bash
# Test TTS directly
./bin/say.sh "Test"           # Cloud
./bin/say-local.sh "Test"     # Local

# Check say.sh script
ls -la bin/say*.sh
```

**Database issues:**
```bash
# Check if migrated
sqlite3 data/jarvis_memory.db "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"

# Run migration
./bin/migrate-proactive-db.py
```

**Wrong mode:**
```bash
# Verify which config is loaded
cat /proc/$(lsof -t -i :8880)/environ | tr '\0' '\n' | grep LLM_PROVIDER
```

---

## Memory API Tests

### 11. Test Memory Stats

```bash
curl -s http://localhost:8880/api/memory/stats | jq
```

**Expected:** Returns total memories, embedding coverage, top categories.

### 12. Test Memory Categories

```bash
curl -s http://localhost:8880/api/memory/categories | jq
```

**Expected:** Returns every category name with its memory count, plus the total memories.

### 13. Test Memory List

```bash
# List all (limited)
curl -s "http://localhost:8880/api/memory?limit=5" | jq '.memories[].key'

# Filter by category
curl -s "http://localhost:8880/api/memory?category=personal" | jq '.memories[].key'
```

### 14. Test Keyword Search

```bash
# Search for "flask"
curl -s "http://localhost:8880/api/memory/search/keyword?q=flask&limit=5" | jq '.memories[] | {key, relevance}'

# Search in specific category
curl -s "http://localhost:8880/api/memory/search/keyword?q=project&category=technical" | jq
```

**Expected:** Returns memories with relevance scores.

### 15. Test Semantic Search

```bash
# Natural language question (uses the active mode's configured threshold)
curl -s "http://localhost:8880/api/memory/search/semantic?q=what%20is%20my%20dog%27s%20name" | jq '{retrieval, memories: [.memories[] | {key, value, similarity, retrieval_score, retrieval_channels}]}'

# With threshold
curl -s "http://localhost:8880/api/memory/search/semantic?q=where%20is%20my%20project&threshold=0.4" | jq
```

**Expected:** Returns hybrid-ranked memories plus retrieval mode, channel, and
fallback diagnostics. Supplying `threshold` overrides the active mode's
`SEMANTIC_SIMILARITY_THRESHOLD` for that request.

### 16. Test Get Memory by ID

```bash
# Get specific memory (replace ID with actual)
curl -s http://localhost:8880/api/memory/273 | jq '.memory'

# Test 404
curl -s http://localhost:8880/api/memory/99999 | jq
```

### 17. Test Create Memory (Non-destructive)

```bash
# Create a test memory
curl -X POST http://localhost:8880/api/memory \
  -H "Content-Type: application/json" \
  -d '{
    "category": "test",
    "key": "api_test_memory",
    "value": "This is a test memory from API testing",
    "importance": 3
  }' | jq

# Verify it exists
curl -s "http://localhost:8880/api/memory/search/keyword?q=api_test_memory" | jq '.memories[0]'
```

### 18. Test Update Memory

```bash
# First get the ID from create response, then:
curl -X PUT http://localhost:8880/api/memory/{ID} \
  -H "Content-Type: application/json" \
  -d '{"value": "Updated test memory", "importance": 4}' | jq
```

### 19. Test Delete Memory

```bash
# Delete the test memory (use ID from step 17)
curl -X DELETE http://localhost:8880/api/memory/{ID} | jq

# Verify deleted
curl -s http://localhost:8880/api/memory/{ID} | jq
# Should return 404
```

---

## Query/Chat API Tests

### 20. Test Quick Query (GET)

```bash
# Time query
curl -s "http://localhost:8880/api/query/quick?q=What%20time%20is%20it" | jq

# Weather query
curl -s "http://localhost:8880/api/query/quick?q=What%20is%20the%20weather" | jq

# Math query
curl -s "http://localhost:8880/api/query/quick?q=What%20is%202%20%2B%202" | jq
```

**Expected:** Returns `ok: true`, `speech`, and `tools_used`.

### 21. Test Quick Query (POST)

```bash
curl -X POST http://localhost:8880/api/query/quick \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the price of Bitcoin?"}' | jq
```

**Expected:** Returns crypto price with `tools_used: ["crypto_price"]`.

### 22. Test Full Query Endpoint

```bash
curl -X POST http://localhost:8880/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is my dogs name?",
    "mode": "cloud",
    "session_id": "api-test-123"
  }' | jq
```

**Expected:** Returns memory recall with `tools_used: ["semantic_recall"]`.

### 23. Test Local Mode

```bash
# Only if Ollama is running
curl -X POST http://localhost:8880/api/query/quick \
  -H "Content-Type: application/json" \
  -d '{"query": "What time is it?", "mode": "local"}' | jq
```

**Note:** Local mode requires Ollama running and takes longer.

### 24. Test Tool Selection

```bash
# Should use calculator
curl -s "http://localhost:8880/api/query/quick?q=sqrt%28144%29" | jq '.tools_used'
# Expected: ["calculator"]

# Should use weather
curl -s "http://localhost:8880/api/query/quick?q=temperature%20outside" | jq '.tools_used'
# Expected: ["weather"]

# Should use memory
curl -s "http://localhost:8880/api/query/quick?q=what%20do%20you%20remember%20about%20my%20projects" | jq '.tools_used'
# Expected: ["semantic_recall"] or ["search_memory"]
```

---

## Conversations API Tests

### 25. Test Conversation Stats

```bash
curl -s http://localhost:8880/api/conversations/stats | jq
```

**Expected:** Returns total_conversations, success_rate, top_tools.

### 26. Test List Conversations

```bash
# List recent 5
curl -s "http://localhost:8880/api/conversations?limit=5" | jq '.conversations[] | {id, query: .user_query, tools: .tools_used}'

# With pagination
curl -s "http://localhost:8880/api/conversations?limit=10&offset=10" | jq '{page, pages, count}'
```

### 27. Test Get Conversation by ID

```bash
# Get specific conversation (use actual ID from list)
curl -s http://localhost:8880/api/conversations/858 | jq '.conversation'

# Test 404
curl -s http://localhost:8880/api/conversations/999999 | jq
```

### 28. Test Recent Conversations

```bash
# Last 30 minutes
curl -s "http://localhost:8880/api/conversations/recent" | jq '.count'

# Last 2 hours
curl -s "http://localhost:8880/api/conversations/recent?minutes=120" | jq '.conversations[].user_query'
```

### 29. Test Search Conversations

```bash
# Search for bitcoin
curl -s "http://localhost:8880/api/conversations/search?q=bitcoin" | jq '.conversations[] | {query: .user_query, response: .jarvis_response}'

# Search for weather
curl -s "http://localhost:8880/api/conversations/search?q=weather&limit=5" | jq '.count'
```

### 30. Test Filter by Tool

```bash
# Filter by crypto_price tool
curl -s "http://localhost:8880/api/conversations?tool=crypto_price&limit=5" | jq '.conversations[].user_query'

# Filter by get_time tool
curl -s "http://localhost:8880/api/conversations?tool=get_time&limit=5" | jq '.count'
```

### 31. Test Sessions List

```bash
curl -s "http://localhost:8880/api/conversations/sessions?limit=5" | jq '.sessions'
```

**Expected:** Returns session_id, message_count, first_message, last_message.

### 32. Test Filter by Success

```bash
# Only successful
curl -s "http://localhost:8880/api/conversations?success=true&limit=5" | jq '.count'

# Only failed
curl -s "http://localhost:8880/api/conversations?success=false&limit=5" | jq '.conversations[].user_query'
```

---

## Quick Test Script

Run all Memory, Query, and Conversations API tests:

```bash
#!/bin/bash
# test-new-apis.sh

BASE="http://localhost:8880"

echo "=== Memory API Tests ==="

echo -e "\n1. Stats:"
curl -s $BASE/api/memory/stats | jq -c '{total: .total_memories, coverage: .embedding_coverage}'

echo -e "\n2. Categories:"
curl -s $BASE/api/memory/categories | jq -c '{categories: .categories, count: .count}'

echo -e "\n3. Keyword Search (flask):"
curl -s "$BASE/api/memory/search/keyword?q=flask&limit=2" | jq -c '.count'

echo -e "\n4. Semantic Search (dog name):"
curl -s "$BASE/api/memory/search/semantic?q=dog%20name&limit=1" | jq -c '.memories[0] | {key, similarity}'

echo -e "\n=== Query API Tests ==="

echo -e "\n5. Time Query:"
curl -s "$BASE/api/query/quick?q=time" | jq -c '{ok, tools: .tools_used}'

echo -e "\n6. Math Query:"
curl -s -X POST $BASE/api/query/quick \
  -H "Content-Type: application/json" \
  -d '{"query": "2+2"}' | jq -c '{speech, tools: .tools_used}'

echo -e "\n7. Memory Query:"
curl -s "$BASE/api/query/quick?q=my%20dogs%20name" | jq -c '{ok, tools: .tools_used}'

echo -e "\n=== Conversations API Tests ==="

echo -e "\n8. Conversation Stats:"
curl -s $BASE/api/conversations/stats | jq -c '{total: .total_conversations, rate: .success_rate}'

echo -e "\n9. Recent Conversations:"
curl -s "$BASE/api/conversations/recent?minutes=60&limit=3" | jq -c '.count'

echo -e "\n10. Search Conversations:"
curl -s "$BASE/api/conversations/search?q=time&limit=3" | jq -c '.count'

echo -e "\n=== Stash API Tests ==="

echo -e "\n11. Stash Stats:"
curl -s $BASE/api/stash/stats | jq -c '{spaces: .total_spaces, files: .total_files, size: .total_size_human}'

echo -e "\n12. List Labels:"
curl -s $BASE/api/stash/labels | jq -c '{count: .count}'

echo -e "\n13. Recent Spaces:"
curl -s "$BASE/api/stash/recent?limit=3" | jq -c '.count'

echo -e "\n14. Search Stash:"
curl -s "$BASE/api/stash/search?q=image&limit=2" | jq -c '{count: .count}'

echo -e "\n15. Filter by Tool:"
curl -s "$BASE/api/stash?tool=generate_image&limit=3" | jq -c '{count: .count, message: .message}'

echo -e "\n=== Canvas API Tests ==="

echo -e "\n16. Canvas Stats:"
curl -s $BASE/api/canvas/stats | jq -c '{pages: .total_pages, size: .total_size_human, with_images: .pages_with_images}'

echo -e "\n17. List Tags:"
curl -s $BASE/api/canvas/tags | jq -c '{count: .count}'

echo -e "\n18. Recent Pages:"
curl -s "$BASE/api/canvas/recent?limit=3" | jq -c '.count'

echo -e "\n19. Search Canvas:"
curl -s "$BASE/api/canvas/search?q=status&limit=2" | jq -c '{count: .count}'

echo -e "\n20. Get Page:"
PAGE_ID=$(curl -s "$BASE/api/canvas/recent?limit=1" | jq -r '.pages[0].page_id')
curl -s "$BASE/api/canvas/$PAGE_ID?include_content=false" | jq -c '{ok, title: .page.title}'

echo -e "\n✅ All tests completed!"
```

Save and run:
```bash
chmod +x test-new-apis.sh
./test-new-apis.sh
```

---

## Success Criteria

✅ All 14 original tests pass in `test-api-endpoints.sh`  
✅ TTS works for high/critical alerts  
✅ Alerts stored in database  
✅ Query filters work  
✅ Auto-sync works between modes  
✅ Interactive docs accessible  
✅ Both cloud and local modes work  

**Memory API:**
✅ Memory API stats returns data  
✅ Memory keyword search finds results  
✅ Memory semantic search finds related memories  

**Query API:**
✅ Query API returns speech and tools_used  
✅ Query API selects correct tools  

**Conversations API:**
✅ Conversations stats returns totals and top tools  
✅ Recent conversations returns data  
✅ Search finds matching conversations  
✅ Filter by tool works  
✅ Sessions list returns session data  

---

**Ready to test?** Run:
```bash
./bin/jarvis-api
./tests/test-api-endpoints.sh
```

**Test new APIs:**
```bash
# Quick memory test
curl -s http://localhost:8880/api/memory/stats | jq '.total_memories'

# Quick query test
curl -s "http://localhost:8880/api/query/quick?q=time" | jq '.speech'

# Quick conversations test
curl -s http://localhost:8880/api/conversations/stats | jq '.total_conversations'
```
