# Jarvis Testing Guide

Comprehensive testing guide for all Jarvis tools, MCP servers, and functionality.

## Quick Start - Automated Testing

### Comprehensive Cloud Test Suite (RECOMMENDED)
Run the full regression test suite (22 tests across 8 sections):

```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
./tests/integration/test-cloud-comprehensive.sh
```

**What it tests:**
- ✅ Prompt caching (verifies 90% cost reduction)
- ✅ Conversation tools (search history, recent conversations)
- ✅ Memory system (remember, recall, search, update)
- ✅ MCP servers (DuckDuckGo, Fetch)
- ✅ OpenCode integration (simple tasks only)
- ✅ API/Network tools (webhooks, crypto, HTTP calls)
- ✅ Multi-turn tasks (cache amplification)
- ✅ Advanced features (verbosity modes, error recovery)

**Results saved to:** `logs/test/test-cloud-comprehensive_TIMESTAMP.{log,json}`

**View results:**
```bash
# Quick summary
jq '.test_run.summary' logs/test/test-cloud-comprehensive_*.json | tail -n 10

# View failed tests
jq '.test_run.tests[] | select(.passed == false)' logs/test/test-cloud-comprehensive_*.json | tail -n 50
```

### Legacy Test Scripts
```bash
# Quick tool tests (cloud mode)
./test-all-tools.sh

# Quick tool tests (local mode with Ollama)
./test-all-tools-local.sh
```

## Prerequisites

```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
```

### Tool RAG System Initialization

**CRITICAL**: After creating/cleaning databases, you MUST sync tool definitions:

```bash
# For cloud mode
./bin/sync-tools.py cloud

# For local mode  
./bin/sync-tools.py local

# Or both
./bin/sync-tools.py cloud && ./bin/sync-tools.py local
```

**Why?** The Tool RAG system requires tool definitions to be indexed in the database with embeddings. Without this, the LLM cannot dynamically discover and use tools.

**When to run:**
- After fresh database creation
- After deleting/recreating databases for tests
- After adding new tools
- After changing tool descriptions
- **Before running tests** if you've manually cleaned the database

**Note**: The test scripts that clean databases (`test-memory-tools.sh`, `test-memory-real-world.sh`, `compare-models.sh`, `test-db-schema.sh`) now automatically run this sync.

**Test scripts that DON'T need sync:**
- `test-all-tools.sh` - Uses existing database
- `test-cloud-comprehensive.sh` - Uses existing database
- `test-tool-rag.sh` - Uses existing database

**If you see "0 tools retrieved" errors**, run sync:
```bash
./bin/sync-tools.py cloud  # or local
```

## Test Configuration

### Response Style
For testing, you may want detailed output:
```bash
# In config/cloud.env or config/local.env
JARVIS_RESPONSE_STYLE="detailed"  # See raw tool output
# or
JARVIS_RESPONSE_STYLE="casual"    # Natural conversational responses (default)
```

## Quick Test - All Systems

```bash
# Test orchestrator is working
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Test MCP servers are loading
./bin/wake-jarvis.py 2>&1 | head -30
# Should see: "✅ duckduckgo: 2 tools" and "✅ fetch: 1 tools"
```

## Local Tools Testing

### 1. Time Tool
```bash
# Direct test
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Expected: Current time in natural language
```

### 2. Crypto Price
```bash
./orchestrator/orchestrator_v2.py cloud "What's the current Bitcoin price?"

# Expected: Current BTC/USD price from CoinGecko
```

### 3. Execute Bash
```bash
./orchestrator/orchestrator_v2.py cloud "List files in the current directory"

# Expected: Directory listing
# Note: This tool requires confirmation unless auto_approve is set
```

### 4. API Call
```bash
./orchestrator/orchestrator_v2.py cloud "Make an API call to check if example.com is up"

# Expected: HTTP response status
```

### 5. Send Webhook
```bash
# Set up a test webhook endpoint first (e.g., webhook.site)
./orchestrator/orchestrator_v2.py cloud "Send a test webhook to https://webhook.site/your-uuid"

# Expected: Confirmation of webhook sent
```

### 6. Check Tool Logs
```bash
# After running some tools
./orchestrator/orchestrator_v2.py cloud "Check the recent tool logs"

# Or directly:
./bin/tool-logs

# Expected: List of recent tool executions with status
```

## Memory Tools Testing

### 7. Remember
```bash
./orchestrator/orchestrator_v2.py cloud "Remember that my favorite color is blue"

# Expected: Confirmation that memory was stored
```

### 8. Recall
```bash
./orchestrator/orchestrator_v2.py cloud "What's my favorite color?"

# Expected: "blue" (or whatever you remembered)
```

### 9. Search Memory
```bash
./orchestrator/orchestrator_v2.py cloud "Search my memories for 'color'"

# Expected: All memories mentioning color
```

### 10. Semantic Recall
```bash
./orchestrator/orchestrator_v2.py cloud "What do you know about my preferences?"

# Expected: Relevant memories found via AI semantic search
```

### 11. Update Memory
```bash
./orchestrator/orchestrator_v2.py cloud "Actually, my favorite color is green now"

# Expected: Confirmation of memory update
```

### 12. Forget
```bash
./orchestrator/orchestrator_v2.py cloud "Forget about my favorite color"

# Expected: Confirmation of memory deletion
```

## MCP Server Testing

### MCP Server Status
```bash
# Check if MCP servers are enabled
cat config/mcp-servers.json | grep enabled

# Check if Docker containers are running (when jarvis is active)
docker ps

# Expected: duckduckgo and fetch containers running
```

### 13. MCP DuckDuckGo Search
```bash
./orchestrator/orchestrator_v2.py cloud "Use DuckDuckGo to search for latest AI news"

# Expected (casual mode): Summarized results with key points
# Expected (detailed mode): 10 search results with URLs
```

### 14. MCP DuckDuckGo Fetch Content
```bash
./orchestrator/orchestrator_v2.py cloud "Fetch the content from example.com"

# Expected: Webpage content as text/markdown
```

### 15. MCP Fetch URL
```bash
./orchestrator/orchestrator_v2.py cloud "Use the fetch tool to get content from example.com"

# Expected: URL content in markdown format
```

## MCP Server Troubleshooting

### Issue: MCP servers not loading
```bash
# Check config
cat config/mcp-servers.json

# Check Docker images
docker images | grep mcp

# Manual MCP test
./bin/test-mcp duckduckgo

# Expected: Tool list from MCP server
```

### Issue: Timeout during startup
```bash
# MCP servers need time to start (2 second wait is built-in)
# If still timing out, check Docker:
docker logs <container-id>

# Increase wait time in lib/tool_schema.py if needed (currently 2s)
```

### Issue: "Container not found" errors
```bash
# Pull MCP images
docker pull mcp/duckduckgo
docker pull mcp/fetch

# Restart jarvis to re-initialize
```

## Full Voice Pipeline Test

### Cloud Mode
```bash
# Start jarvis
jarvis

# Say: "Hey Jarvis"
# Then: "What time is it?"

# Expected:
# 1. Wake word detection
# 2. Audio recording
# 3. OpenAI transcription
# 4. Tool execution
# 5. Natural response
# 6. TTS playback
```

### Local Mode
```bash
# Start jarvis local
jarvis-local

# Say: "Hey Jarvis"
# Then: "What time is it?"

# Expected:
# 1. Wake word detection (OpenWakeWord)
# 2. Audio recording
# 3. Faster-Whisper transcription
# 4. Tool execution (Ollama)
# 5. Natural response
# 6. Kokoro TTS playback
```

## Response Style Testing

### Test Casual Mode (Default)
```bash
export JARVIS_RESPONSE_STYLE="casual"
./orchestrator/orchestrator_v2.py cloud "Search for movie theaters in Portland"

# Expected: Natural summary, NO URLs spoken
# "I found several theaters in Portland. The main ones are..."
```

### Test Detailed Mode
```bash
export JARVIS_RESPONSE_STYLE="detailed"
./orchestrator/orchestrator_v2.py cloud "Search for movie theaters in Portland"

# Expected: Raw search results with all URLs and data
```

### Test Auto Mode
```bash
export JARVIS_RESPONSE_STYLE="auto"
./orchestrator/orchestrator_v2.py cloud "What time is it?"

# Expected: Raw output for simple tools
```

## Error Recovery Testing

### Test Retry Logic
```bash
# Cause a tool to fail (e.g., bad API call)
./orchestrator/orchestrator_v2.py cloud "Get the price of a cryptocurrency that doesn't exist"

# Expected: Retry attempt, then graceful error message
```

### Test Self-Correction
```bash
# Give ambiguous or slightly wrong input
./orchestrator/orchestrator_v2.py cloud "Call the bitcoin API"

# Expected: Jarvis clarifies or interprets intelligently
```

## Performance Testing

### Tool Execution Speed
```bash
# Time a simple tool
time ./orchestrator/orchestrator_v2.py cloud "What time is it?" --json

# Expected: < 2 seconds for local tools
# Expected: < 5 seconds for MCP tools (includes Docker startup)
```

### MCP Startup Time
```bash
# Time full startup with MCP
time python3 -c "
import sys
sys.path.insert(0, 'lib')
from tool_schema import ToolRegistry
r = ToolRegistry('skills', 'config/mcp-servers.json')
print(f'{len(r.tools)} tools loaded')
"

# Expected: < 5 seconds (2s MCP wait + discovery)
```

## Database Testing

### Memory Database Integrity
```bash
# Check schema
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import get_memory_db
db = get_memory_db()
cursor = db.conn.cursor()
cursor.execute(\"SELECT sql FROM sqlite_master WHERE type='table'\")
for table in cursor.fetchall():
    print(table[0])
db.close()
"

# Expected: knowledge_base and conversations tables with all columns
```

### Embedding Generation
```bash
# Test embedding creation
./orchestrator/orchestrator_v2.py cloud "Remember that I love pizza"

# Check embedding was created
python3 -c "
import sys
sys.path.insert(0, 'lib')
from memory_db import get_memory_db
db = get_memory_db()
cursor = db.conn.cursor()
cursor.execute('SELECT key, length(embedding) FROM knowledge_base ORDER BY id DESC LIMIT 1')
row = cursor.fetchone()
print(f'Memory: {row[0]}, Embedding size: {row[1]} bytes')
db.close()
"

# Expected: Embedding should be > 0 bytes
```

## Tool Logging Testing

### Check Tool Logs
```bash
# View today's log file
cat logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl

# Use the log viewer
./bin/tool-logs --limit 5

# Expected: JSONL format with timestamps, tool names, results
```

### Verify Log Rotation
```bash
# Check log files
ls -lh logs/tools/

# Expected: One file per day, JSONL format
```

## JSON Output Testing

### Verify Clean JSON
```bash
# Test --json flag
./orchestrator/orchestrator_v2.py cloud "What time is it?" --json | jq '.'

# Expected: Valid JSON, no verbose output mixed in
```

### Integration with Shell Scripts
```bash
# Test the pipeline
echo "What time is it?" | ./bin/question-orchestrator.sh

# Expected: No jq parse errors, clean flow
```

## Test Result Interpretation

### Understanding Pass/Fail

**✅ PASSED** = Tool executed successfully AND expected keyword found in response
**❌ FAILED** = Either tool error OR keyword not found

**Common false failures:**
- Keyword matching too strict (e.g., expecting "200" but got "successful")
- Semantic differences (e.g., expecting "hue" but model used "color")
- Response style variations (casual vs detailed mode)

**How to verify actual functionality:**
```bash
# Check if tool executed successfully (ok: true)
jq '.test_run.tests[] | {name: .name, ok: .ok, speech: .speech}' logs/test/test-cloud-comprehensive_*.json | tail -n 50

# If ok=true but passed=false, it's just a keyword mismatch
# Update test expectations in test-cloud-comprehensive.sh
```

### Cache Metrics

**Expected cache behavior:**
- **Test 1-3**: Cache WRITE on first request (~10,884 tokens)
- **All subsequent tests**: Cache READ (~10,884 tokens)
- **Multi-turn tests**: Higher cache reads (~16,326 tokens)

**Savings calculation:**
- Cache write: 3.75¢ per 1M tokens (25% markup)
- Cache read: 0.30¢ per 1M tokens (90% discount)
- Regular input: 3.00¢ per 1M tokens

**Example:**
```
10,884 tokens cached
Without cache: 10,884 * $3.00 / 1M = $0.033
With cache: 10,884 * $0.30 / 1M = $0.003
Savings: $0.030 per request (91% reduction)
```

### Test Run Cost Analysis

```bash
# Total test cost
jq '[.test_run.tests[].cost_usd] | add' logs/test/test-cloud-comprehensive_*.json | tail -n 1

# Total savings
jq '[.test_run.tests[].cache_savings_usd] | add' logs/test/test-cloud-comprehensive_*.json | tail -n 1

# Average cost per test
jq '[.test_run.tests[].cost_usd] | add / length' logs/test/test-cloud-comprehensive_*.json | tail -n 1
```

## Tool RAG Troubleshooting

### Issue: "Tool not retrieved" or LLM using wrong tools
**Symptoms:**
- LLM uses `get_time` instead of the correct tool
- Tests fail with wrong tool selection
- Debug shows 0 or very few tools retrieved

**Fix:**
```bash
# 1. Verify tool embeddings exist
find skills -name '*.tool.json' | wc -l   # repo tool count (~77)
sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM tool_definitions WHERE embedding IS NOT NULL;"
# Embedding count should match your enabled tools (after ./bin/sync-tools.py)

# 2. If 0 or low, resync:
./bin/sync-tools.py cloud

# 3. Test again
./orchestrator/orchestrator_v2.py cloud "What is the price of Bitcoin?"
```

### Issue: Tool definitions table doesn't exist
**Symptoms:**
- Error: `no such table: tool_definitions`
- Fresh database from backup

**Fix:**
```bash
# The table is created automatically on first MemoryDB connection
# Just run sync:
./bin/sync-tools.py cloud
```

### Issue: Tests fail after database restore from backup
**Symptoms:**
- Restored old backup, tests now fail
- Tool RAG not working after restore

**Fix:**
```bash
# Old backups don't have tool_definitions table
# The table will be auto-created, but embeddings need sync:
./bin/sync-tools.py cloud
```

## Known Issues & Workarounds

### Test Keyword Matching
**Issue:** Some tests fail due to strict keyword matching  
**Example:** Expecting "remember" but LLM says "saved to memory"  
**Impact:** False failure (functionality works)  
**Solution:** Update test expectations in `test-cloud-comprehensive.sh`

### Semantic Recall Test Sensitivity
**Issue:** Semantic recall requires good synonym understanding  
**Example:** "hue" vs "color" may not match semantically  
**Impact:** Test may fail if embeddings don't link concepts  
**Solution:** Use more direct questions or train embeddings better

### MCP Discovery Running Twice
**Issue:** MCP servers discovered in both router and executor  
**Impact:** ~2 seconds extra startup time  
**Status:** Known, low priority (system works fine)  
**Workaround:** None needed - functionality is correct

### Local Mode Timeout with Weak Models
**Issue:** Ollama models that aren't tool-optimized may time out  
**Solution:** Use a tool-capable Ollama model such as `qwen3.5:latest`, `qwen3-coder`, or `gemma4`  
**Config:** `OLLAMA_MODEL` in `config/local.env` (see `config/local.env.example`)

### Memory Embedding Generation
**Issue:** Embeddings only generated on creation, not bulk  
**Solution:** For existing memories, delete and re-remember  
**Future:** Bulk embedding regeneration tool

## Test Checklist

Use this for a comprehensive test run:

- [ ] **Local Tools**
  - [ ] get_time
  - [ ] crypto_price
  - [ ] execute_bash
  - [ ] api_call
  - [ ] send_webhook
  - [ ] check_tool_logs

- [ ] **Memory Tools**
  - [ ] remember
  - [ ] recall
  - [ ] search_memory
  - [ ] semantic_recall
  - [ ] update_memory
  - [ ] forget

- [ ] **MCP Tools**
  - [ ] mcp_duckduckgo_search
  - [ ] mcp_duckduckgo_fetch_content
  - [ ] mcp_fetch_fetch

- [ ] **Voice Pipeline**
  - [ ] Wake word detection
  - [ ] Audio recording (both modes)
  - [ ] STT (OpenAI & Faster-Whisper)
  - [ ] Tool execution
  - [ ] TTS (OpenAI & Kokoro)

- [ ] **Response Formatting**
  - [ ] Casual mode (natural speech)
  - [ ] Detailed mode (raw output)
  - [ ] Auto mode (smart selection)

- [ ] **Error Handling**
  - [ ] Tool failures with retry
  - [ ] MCP server errors
  - [ ] Memory errors

- [ ] **Database**
  - [ ] Memory creation
  - [ ] Memory retrieval
  - [ ] Embedding generation
  - [ ] Conversation logging

## Tool RAG System Testing

### Verify Tool Retrieval
```bash
# Test that non-ghost tools are dynamically retrieved
./tests/integration/test-tool-rag.sh

# Expected: 8/8 tests pass
# - 4 non-ghost tools retrieved and used
# - 3 ghost tools always available
# - Multi-turn self-healing verified
```

### Debug Tool Retrieval
```bash
# See what tools are retrieved for a query
./bin/debug-tool-rag.py cloud "What is the price of Bitcoin?"

# Expected output:
# - Similarity scores for all tools
# - Which tools pass the threshold
# - Exactly what the LLM receives
# - Recommendations for threshold tuning
```

### Verify Tool Embeddings
```bash
# Check if tools are indexed
find skills -name '*.tool.json' | wc -l   # repo tool count (~77)
sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM tool_definitions WHERE embedding IS NOT NULL;"

# Embedding count should match enabled tools; if 0: Run ./bin/sync-tools.py cloud
```

### Multi-Turn Self-Healing Test
```bash
# Test LLM can diagnose and fix errors through multiple attempts
./tests/integration/test-self-healing.sh

# Expected behaviors:
# - LLM checks logs after failures
# - Retries with corrected parameters  
# - Uses fallback strategies (e.g., semantic_recall → search_memory)
# - Adapts to error messages
```

## Continuous Testing

### After Code Changes (CRITICAL)
**Always run the comprehensive test suite** after modifying code:

```bash
./tests/integration/test-cloud-comprehensive.sh
```

**Why?** Because you might break something else while fixing one thing. The comprehensive test catches:
- Broken tool calls
- Memory system regressions
- MCP server failures
- Cache implementation bugs
- Response format changes
- Multi-turn orchestration issues

**Expected:** 100% pass rate (22/22 tests)

### Daily Quick Check
```bash
# 30-second smoke test
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py cloud "Search for AI news"
./orchestrator/orchestrator_v2.py cloud "Remember I tested today"
```

### Weekly Full Test
```bash
# Run comprehensive test + voice pipeline test
./tests/integration/test-cloud-comprehensive.sh
# Then manually test voice mode
jarvis
```

### Before Deploying/Merging
1. Run comprehensive test suite
2. Check test results: `jq '.test_run.summary' logs/test/test-cloud-comprehensive_*.json | tail -n 10`
3. Verify cache metrics are correct
4. Manually test 2-3 voice interactions

## Reporting Issues

When reporting bugs, include:
1. Command run
2. Expected result
3. Actual result
4. Mode (cloud/local)
5. Response style setting
6. Tool logs (if relevant)
7. Docker status (for MCP issues)

Example:
```
Command: ./orchestrator/orchestrator_v2.py cloud "Search web"
Expected: Search results
Actual: Timeout after 30s
Mode: cloud
Response Style: casual
Tool Logs: [attach]
Docker: Containers running (docker ps output attached)
```

