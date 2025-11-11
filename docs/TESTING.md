# Jarvis Testing Guide

Comprehensive testing guide for all Jarvis tools, MCP servers, and functionality.

## Prerequisites

```bash
cd /home/boss/jarvis-voice
source ~/jarvis-venv/bin/activate
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
./bin/wake_jarvis.py 2>&1 | head -30
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

## Known Issues & Workarounds

### MCP Discovery Running Twice
**Issue:** MCP servers discovered in both router and executor  
**Impact:** ~2 seconds extra startup time  
**Status:** Known, low priority (system works fine)  
**Workaround:** None needed - functionality is correct

### Local Mode Timeout with Weak Models
**Issue:** Ollama models that aren't tool-optimized may time out  
**Solution:** Use `llama3-groq-tool-use:latest` or similar  
**Config:** `OLLAMA_MODEL` in `config/local.env`

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

## Continuous Testing

### Daily Quick Check
```bash
# 30-second smoke test
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py cloud "Search for AI news"
./orchestrator/orchestrator_v2.py cloud "Remember I tested today"
```

### Weekly Full Test
Run through entire test checklist (30 minutes)

### After Code Changes
Test affected components + integration test

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

