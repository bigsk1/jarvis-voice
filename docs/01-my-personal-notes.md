## My Notes, Ideas, Concerns

### Notes

```bash
./orchestrator/orchestrator_v2.py cloud "Use playwright and download the details about this repo https://github.com/bigsk1/opencode-doc and save to my intel folder"

./orchestrator/orchestrator_v2.py cloud "Check my service logs for any errors in the last hour, summarize them, and email boss the summary"
./orchestrator/orchestrator_v2.py cloud "Look up whether the domain bigsk1.com has any outages reported online"
./orchestrator/orchestrator_v2.py cloud "Search my intel for anything related to my latest birthdate, update the memory with the latest one found, can't have a birthday two different dates, the most recent one in db is correct"
./orchestrator/orchestrator_v2.py cloud "Scan my recent conversations for references to Docker"
./orchestrator/orchestrator_v2.py cloud "Fetch external data about Ubuntu 24.04 kernel regressions and correlate it with my current system"
./orchestrator/orchestrator_v2.py cloud "Find any unresolved reminders older than 1 day, acknowledge them, and create a intel file about it"

./orchestrator/orchestrator_v2.py cloud "Check my opencode sessions for any recent builds that were done, verify that it was previously saved in memory"
./orchestrator/orchestrator_v2.py cloud "Fetch the Cloudflare API docs, extract rate-limit rules via the sequential thinking tool, and add notes to my intel"

./orchestrator/orchestrator_v2.py cloud "Query all alert sources, filter for ones mentioning 'kokoro', and email boss a prioritized list"

```

```bash
- Note on the alerts system the title is what will be read aloud, llm can search for source info on follow up questions but  when webhook comes in will say "You have one pending high severity /test alert from cloud/." test alert from cloud is the title that was sent.


- when running local it shows usd costs for ollama model, should be 0 cost is local, `usage` field  was added in local mode? or is it because i am using shortcut command or local cli json? , is because in json mode is why, solution dont worry about it normal non jason mode doesnt show it. 

jarvis-cli-json local "what is your system prompt?"
{
  "speech": "I can't share my system prompt, but I can assist with tasks and information.",
  "ok": true,
  "tools_used": [],
  "data": {},
  "usage": {
    "input_tokens": 4470,
    "output_tokens": 40,
    "cost_usd": 0.01389, <- is local $0 costs>
    "cache_creation_tokens": 0,
    "cache_read_tokens": 0,
    "cache_savings_usd": 0.0
  }
}
------------
none type error using qwen2.5 - solution dont use qwen2.5 is weak. 

(jarvis-venv) boss@fred:~/jarvis-voice$ cd /home/boss/jarvis-voice && ./orchestrator/orchestrator_v2.py local "What time i
s it?" 2>&1 | head -20
Ollama API error: 'NoneType' object has no attribute 'replace'
🎯 Processing: 'What time is it?'
📡 Mode: local
🤖 Model: qwen2.5:7b



check opencode session is used after i asked jarvis to use opencode to make something looking at tool logs
 "Found 5 recent OpenCode session(s): Jarvis: Create a simple Python script named hello_world.py (unknown mode), Jarvis: fix cross-origin errors (unknown mode),
 we need to make sure jarvis can get current session id or know what part of the build process opencode is in to know when task is complete and respond back with details ect. if 
 jarvis only checks opencode logs and see it is building X but doesnt mean it is complete and opencode could be still building and jarvis replaces all done, but is it? and working? issues? revisions opencode still doing stuff? or is everything in order? in opencode logs i see sessions id for opencode
 {"timestamp": "2025-11-21T04:07:08.869665", "event": "session_complete", "session_id": "ses_559b08a49ffeA6lkBAAz4fY28v", "success": true, "result_summary": "Task completed in 12210ms",}

```


----


### Ideas

```bash
Dashboarding the "Brain"

You already have Grafana/Loki. You should add an Intelligence Panel.

    Metric: intelligence_hit_rate (How often was a retrieved insight actually used by the Router?).

    Metric: insight_growth (Are we learning too fast? Might be noise).

    Visual: A table showing the last 5 "Learned Lessons." This makes the "Self-Learning" aspect visible to you, the user, which reinforces the "Full Awareness" feeling.

```

### Concerns

```bash
- not all jarvis-local features and tools/mcp work because a few reasons cloud uses better models and when designing and adding code / testing we focus on cloud version mostly. 

### Commands for running 

# Terminal 1: Reactive Voice Mode (already running)
./jarvis                  # Listens for "Hey Jarvis" wake word
                          # Processes voice queries
                          # Can now also query alerts via voice!

# Terminal 2: Proactive API Server (runs separately)
./bin/jarvis-api          # Receives webhooks from external systems
                          # Stores alerts/reminders in database
                          # Speaks urgent alerts via TTS
                          # Provides REST API endpoints

# Terminal 3: Background Services (NEW - what we'll build)
./bin/jarvis-services     # Follow-up daemon (re-alerts if not acknowledged)
                          # Self-healing daemon (checks auto_resolve_url)
                          # Reminder scheduler (triggers time-based reminders)
                          
- Originally was going to have intel api route and there is all ready intel related  columns in db, under reminders, some idea to be able to update modify or add , delete intel files in which jarvis has tools to injest into db for direct access. 
```


```bash
./tests/integration/test_intelligence_sandbox.py --verbose
./tests/integration/test_intelligence_sandbox.py --test helpfulness
./tests/integration/test_intelligence_sandbox.py --test analysis


# Enable/Disable (edit config file)
JARVIS_INTELLIGENCE=true   # Enable (default)
JARVIS_INTELLIGENCE=false  # Disable

# Check status
python3 -c "from lib.intelligence import get_intelligence_layer; print(get_intelligence_layer().get_stats())"

# Reset learning (start fresh)
rm data/jarvis_intelligence.db  # Next run recreates it empty

Health checks for intelligence layer
# Check single mode
./bin/check-intelligence-health.py cloud
./bin/check-intelligence-health.py local

# Check both
./bin/check-intelligence-health.py --both

# JSON output
./bin/check-intelligence-health.py --json

# Sync insights (regenerates embeddings)
./bin/sync-intelligence-db.py local   # cloud → local (1536 → 768)
./bin/sync-intelligence-db.py cloud   # local → cloud (768 → 1536)

# Reset a database
./bin/sync-intelligence-db.py --reset cloud


# Today's logs for intelligence layer
cat logs/intelligence/intelligence-$(date +%Y-%m-%d).jsonl | jq '.'

# Just events
cat logs/intelligence/intelligence-*.jsonl | jq -c '.event'

# Reflection responses only
cat logs/intelligence/intelligence-*.jsonl | jq 'select(.event == "reflection_response")'

# Trigger reflection
curl -X POST "http://192.168.70.228:8880/api/intelligence/reflect?batch_size=5"

# View insights
curl http://192.168.70.228:8880/api/intelligence/insights | jq '.insights'

# View meta-knowledge
curl http://192.168.70.228:8880/api/intelligence/meta-knowledge | jq '.'

```

### Commands for testing

```bash
activate env 
source ~/jarvis-venv/bin/activate

# Test sync manually
./bin/sync-memory-db.py --from cloud --to local

# Or start API/services and sync happens automatically
./bin/jarvis-api --local
./bin/jarvis-services --local
./bin/jarvis-canvas
./bin/jarvis-dashboard

no db run - cloud or local  both to get all tables made and to create embedding for tools and mcp tools
 ./bin/sync_tools.py cloud
 ./bin/sync_tools.py local

test all tools
cd /home/boss/jarvis-voice/tests/integration && ./test-all-tools.sh

test all tools local
cd /home/boss/jarvis-voice/tests/integration && ./test-all-tools-local.sh

test orchestrator cloud for time
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "What time is it?"

test orchestrator local for time tool
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py local "What time is it?"

test orchestrator cloud using a specific tool send_webhook
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "use send_webhook to send a test webhook to https://n8n-roscossscggc4sogsw4s0gck.bigsk1.com/webhook/webhook-logger and short summary of the response and save the webhook url to memory"

test orchestrator local using a specific tool send_webhook
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py local "use send_webhook to send a test webhook to https://n8n-roscossscggc4sogsw4s0gck.bigsk1.com/webhook/webhook-logger and short summary of the response and save the webhook url to memory"

test orchestrator cloud using tool search_memory
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "search memory for the last webhook sent and it's url"


test opencode
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "use opencode to list files"

test opencode local
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py local "use opencode to list files"

test mcp
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/test-mcp

test mcp local
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/test-mcp --manager


### Commands for stopping tetris server
pkill -f "server.py" && echo "✅ Server stopped" || echo "No server running"


### Commands for checking if tetris server is running
lsof -i :5000 | grep LISTEN | awk '{print "✅ Flask server running on port 5000 (PID: " $2 ")"}'
```

### CLI Mode (No Voice/Speaker) - Travel Mode

**🚀 To enable CLI commands in your CURRENT terminal:**
```bash
source ~/.bashrc
```

**Note:** These are bash **functions** (not aliases) that work in any new terminal automatically. If you get "command not found", run the source command above.

**Basic Usage - Clean Output:**
```bash
# Cloud mode (OpenAI/Anthropic)
jarvis-cli "what time is it?"
jarvis-cli "what's the bitcoin price?"
jarvis-cli "search my memory for tetris"

# Local mode (Ollama)
jarvis-local-cli "what time is it?"
jarvis-local-cli "search my memory for opencode"
jarvis-local-cli "use send_webhook to post test data to https://n8n-roscossscggc4sogsw4s0gck.bigsk1.com/webhook/webhook-logger"
# Remember something
jarvis-local-cli "remember that the n8n local webhook url is http://192.168.70.226:5678/webhook/process-data"
```

**JSON Output - For Debugging:**
```bash
# See full JSON response with tool metadata
jarvis-cli-json "what time is it?"
jarvis-local-cli-json "search my memory for tetris"

# Extract specific fields
jarvis-cli-json "bitcoin price" | jq '.speech'
jarvis-cli-json "bitcoin price" | jq '.tools_used'
jarvis-cli-json "bitcoin price" | jq '.ok, .speech, .tools_used'
```

**Testing All Memory Tools:**
```bash
# Remember something
jarvis-cli "remember that the n8n webhook url is https://n8n-roscossscggc4sogsw4s0gck.bigsk1.com/webhook/webhook-logger"

# Remember something
jarvis-cli "remember that the n8n webhook url is http://192.168.70.226:5678/webhook/process-data"

# Search memory
jarvis-cli "search memory for webhook"

# Recall memory by keyword
jarvis-cli "recall memory about n8n"

# Semantic recall
jarvis-cli "what webhooks do I have saved?"

# Update memory
jarvis-cli "update memory about n8n webhook url to https://new-url.com"

# Forget memory
jarvis-cli "forget memory about old webhook"
```

**Testing OpenCode:**
```bash
# Check OpenCode is running
systemctl status opencode-jarvis.service

# Cloud mode
jarvis-cli "use opencode to list files in the projects directory"
jarvis-cli "use opencode to show me what projects exist"
jarvis-cli "use opencode to read the tetris game readme"

# Local mode
jarvis-local-cli "use opencode to list workspace files"
```

**Multi-Turn Tasks:**
```bash
# Build and verify
jarvis-cli "use opencode to build a simple calculator app, then use bash to verify it was created"

# Send webhook and remember
jarvis-cli "send test webhook to n8n logger and remember the response"

# Complex task
jarvis-cli "search my memory for tetris, then use bash to check if the server is running on port 5000"
```

**Testing Different Response Styles:**
```bash
# Edit config/cloud.env or config/local.env and change JARVIS_RESPONSE_STYLE
# Options: casual, detailed, auto

# Casual (10-15 words, concise)
JARVIS_RESPONSE_STYLE=casual jarvis-cli "what time is it?"

# Detailed (full context, all data)
JARVIS_RESPONSE_STYLE=detailed jarvis-cli "what time is it?"

# Auto (adapts based on task complexity)
JARVIS_RESPONSE_STYLE=auto jarvis-cli "what time is it?"
```

**Quick Iteration Testing:**
```bash
# Test same query 3 times
for i in 1 2 3; do echo "=== Test $i ==="; jarvis-cli "what time is it?"; echo ""; done

# Test different tools
jarvis-cli "time"; jarvis-cli "bitcoin price"; jarvis-cli "search memory for tetris"

# Compare cloud vs local
echo "CLOUD:"; jarvis-cli "bitcoin price"
echo "LOCAL:"; jarvis-local-cli "bitcoin price"
```

**Troubleshooting:**
```bash
# Check for JSON parse errors
jarvis-cli-json "what time is it?" 2>&1 | grep -i error

# See raw output (no jq)
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && python3 orchestrator/orchestrator_v2.py cloud "what time is it?" --json

# Check logs
tail -f logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl
```

**Performance Testing:**
```bash
# Time execution
time jarvis-cli "what time is it?"

time jarvis-local-cli "what time is it?"

# Test complex task
time jarvis-cli "use opencode to list all python files in the projects directory"
```

**Quick Verification (Test All CLI Commands):**
```bash
# Test all 4 functions work
jarvis-cli "time"
jarvis-local-cli "time"
jarvis-cli-json "time" | jq '.ok'
jarvis-local-cli-json "time" | jq '.speech'
```

**Thinking cmands**
## test thinking models with --debug-thinking

```bash
# Test 1: Cloud with thinking
./orchestrator/orchestrator_v2.py cloud "What time is it?" --debug-thinking

# Test 2: Local with thinking (deepseek-r1)
./orchestrator/orchestrator_v2.py local "What is 2+2?" --debug-thinking

# Test 3: Grey area scenario
./orchestrator/orchestrator_v2.py cloud "I'm excited about the new Predator movie" --debug-thinking

# Test 4: View logs
cat logs/thinking/$(date +%Y-%m-%d)_decisions.jsonl | jq '.'
```

[thinking](docs/THINKING_MODE_TESTING.md)

---

## Intelligence Layer - Future Exploration (2025-11-27)

### To Explore Later

1. **User Bias Injection** - Let users override tool preferences
   - Via config file or `jarvis-intel/user_preferences.md`
   - "Always use execute_bash for server checks"
   - "Never use search_memory for real-time data"

2. **"Last Tool = Success" Problem**
   - Current: assumes last tool used = the successful one
   - Reality: middle tools might have provided the actual answer
   - Need: content attribution (which tool output appeared in response)

3. **Reflection Model Problem** ⚠️ IMPORTANT
   - **Same model grading itself** = reinforces bad behavior!
   - Same LLM that made the decision is evaluating if it was good
   - If it thought it was right during the task, it'll think it's right during reflection
   - **Better approach**: Smarter model (xAI/Anthropic) analyzes less capable model's actions
   - Current game plan: Run reflections in CLOUD mode (smart LLM), sync to LOCAL
   - This way Qwen/local models benefit from Grok/Claude's analysis
   - **The insight persistence IS the value** - fresh sessions forget, but intelligence.db remembers

4. **Response Content Not Captured**
   - Reflection only sees: query + tools + success/fail
   - Doesn't see: actual LLM response text
   - Can't evaluate: "Was the ANSWER correct?" only "Did the tool crash?"
   - Future fix: Add `llm_response` to experience records

5. **Beyond Tool Selection** → See `docs/Psychological-Profile-Ideas.md`
   - Learn WHEN to save to memory (not just which tool)
   - Learn verbosity preferences (concise vs detailed)
   - Learn communication style (serious, humor, emotional)
   - Understand user shortcuts ("the usual", "the thing")
   - **Phase 2A**: User Model table in memory_db (scalar traits 0.0-1.0)
   - **Phase 2B**: Style reflection (detect correction patterns)
   - **Phase 2C**: Dreaming/offline learning (process failures at night)

6. **Auto-Parameter Tuning**
   - Run test scenarios to measure intelligence performance
   - Auto-adjust: `INTELLIGENCE_LEARNING_RATE`, `INTELLIGENCE_MIN_CONFIDENCE`
   - Goal: find optimal values for MY usage patterns

7. **CRITICAL GAP: Insight Usage Tracking** (2025-11-28)
   - `record_insight_usage()` EXISTS but is NEVER CALLED!
   - All insights have `times_applied = 0`, `times_helpful = 0`
   - Parameters `decay_rate`, `learning_rate` have NO EFFECT until this is fixed
   - **FIX NEEDED**: After interaction, compare outcome to applied insights
   - **Implementation**: Track which insights were retrieved → check outcome → update

8. **Hardcoded Tool Categories**
   - Tool categories in reflection prompt are hardcoded
   - Won't scale with 100+ tools from Tool RAG
   - **Future**: Auto-generate categories from tool metadata/tags

### Quick Commands

```bash
# Check intelligence health
./bin/check-intelligence-health.py --both

# Trigger pending reflections
python3 -c "from lib.intelligence_hooks import trigger_reflection; trigger_reflection(10)"

# Run hard intelligence tests (complex scenarios)
./tests/integration/test-intelligence-hard.sh cloud

# View current insights with usage stats
sqlite3 data/jarvis_intelligence.db "
SELECT constraint_type, description, confidence, 
       times_applied, times_helpful, times_failed 
FROM insights ORDER BY times_applied DESC"

# View insight effectiveness (once tracking works)
sqlite3 data/jarvis_intelligence.db "
SELECT description, 
       ROUND(100.0 * times_helpful / NULLIF(times_applied, 0), 1) as success_rate,
       times_applied
FROM insights WHERE times_applied > 0"

# Reset intelligence (careful!)
./bin/sync-intelligence-db.py --reset cloud
```

[Health-check-for-Memory](docs/EMBEDDING_HEALTH_CHECKS.md)


# Intelligence Maintenance Commands

```bash
# All jobs with log tail
./bin/run-intelligence-maintenance.py --watch

# Individual jobs
./bin/run-intelligence-maintenance.py --decay
./bin/run-intelligence-maintenance.py --anomaly
./bin/run-intelligence-maintenance.py --meta

# All jobs
curl -X POST http://192.168.70.228:8880/api/intelligence/maintenance/all

# Individual
curl -X POST http://192.168.70.228:8880/api/intelligence/maintenance/decay
curl -X POST http://192.168.70.228:8880/api/intelligence/maintenance/anomaly
curl -X POST http://192.168.70.228:8880/api/intelligence/maintenance/meta-cognition

# View meta-knowledge
curl http://192.168.70.228:8880/api/intelligence/meta-knowledge

```

### LogQL Queries for Analysis

```bash
# See all maintenance results
{job="jarvis", log_type="intelligence"} | json | event="maintenance_run"

# Track tool bias evolution
{job="jarvis", log_type="intelligence"} | json | event="insights_applied" 

# Find content quality issues
{job="jarvis", log_type="intelligence"} | json | event="reflection_response" | response_matched_tool_data=false
```

# Status Phrases testing

```bash
# Quick test
./bin/say-status.sh "BUCKLE UP BUTTERCUP" true

# Or for local
./bin/say-status-local.sh "THE VOID STARES BACK" true
```

# View cache stats
```bash
./bin/status-cache stats

# Clear cache (if you change voice settings)
./bin/status-cache clear

# Pre-warm cache (generate all phrases upfront)
./bin/status-cache warm cloud   # Cloud mode
./bin/status-cache warm local   # Local mode
```2025-11-29: Fixed insight tracking - negative constraints now correctly marked as NOT helpful when contradicted by successful tool usage
