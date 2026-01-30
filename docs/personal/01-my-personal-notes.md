## My Notes, Ideas, Concerns

Need to do more testing with local mode and workflows, needs work. 

bookmark search from fire fox, able to find and even open in other devce browser a boomark or at least provide exact name to type to open bookmark, so you provide a general idea of what you think you saved and llm will find it. 


audio on web isnt saved for mic like it is for terminal/tui/jarvis it seems in audio/cloud/mic , is there auto cleanup of old audio files?

when using openai image1.5 need to seperate the usd cost in token count as it costs more, this goes for any other than noraml tool or features involing higher token costs

basic auth or user/password for all web ui servers, web,memory,Intelligence. 

jarvis to opencode, need to see if jarvis can follow and get all opencode user logs ( what a user would see in a tui) and jarvis can stream and keep track of progress, and stop opencode and correct if needed just like a user can do in TUI but using opencode api's. need to check current setup if it is just send openocde task, is waiting with no opencode responces? jarvis can send open session log tool to check progress, but cant stop opencode. Jarvis needs to be basiclly me working with opencode directly. 

E. Tool enable/disable in UI	🔧 Toggle tools on/off from Settings → Tools tab

daily recap tool idea, ( "Jarvis give me a recap" ) server status, alerts reminders if any, issues, weather, big cryptocurrency price changes, certain stocks tesla, because of the length of responce we should still provide a summary of the responce but full details on a canvas to view or review. 

create songs tool, use suno api? 

youtube transcripts tool, i guess web ui is good for this, pasting youtube url, jarvis gets trasncript, uses stash, saves to memory already of using statsh. 

imdb search tool, for interesting movies, tv shows, etc. i might like based on interets or a topic at the time, can narrow it down. 

metadata_scrubber	Remove Exif/GPS data from images or PDF metadata for privacy.	"Clean the metadata from these photos before I upload them."


### Notes

./bin/start
to start all services, api, web

jarvis openocde is systemd
jarvis unify is systemd

jarvis blinko is docker auto start
jarvis grafana, promtail, promethus, loki is docker auto start



On a reflection intellegence it shows user retries, and the reflection is graded on if there was a user retry and not satisfied with responce, however i dont think the is added yet, as a reflection is doing one llm session at a time, it doesnt know if the next question to the llm was not satisfied with the responce and user retried, so it is not graded on that. It seems if a tool has 200 status menaing ti ran and no error the user is satisfied? this whole concept needs evalution, what is currently happening- is it working?, what should happen to satisfy this feature, do we need this feature? 

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

```

----

### Ideas



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

#  Jarvis web
./bin/jarvis-web    
                          
 
 # Terminal With speech output
./orchestrator/orchestrator_v2.py cloud "What time is it?" --speak
./orchestrator/orchestrator_v2.py local "Turn up my speaker volume" --speak
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
curl -X POST "http://localhost:8880/api/intelligence/reflect?batch_size=5"

# View insights
curl http://localhost:8880/api/intelligence/insights | jq '.insights'

# View meta-knowledge
curl http://localhost:8880/api/intelligence/meta-knowledge | jq '.'

```

### Commands for testing

```bash
activate env 
source ~/jarvis-venv/bin/activate

# Test sync manually
./bin/sync-memory-db.py --from cloud --to local

# Or start API/services and sync happens automatically
./bin/jarvis-api   ( does sync from cloud to local) takes time before ready and cant just run services right after
./bin/jarvis-services  ( does sync from cloud to local )  takes time before ready
./bin/jarvis-canvas
./bin/jarvis-web
./bin/jarvis-memory

# this covers all apis and services and ui's and memory browser
./bin/start              # Start ALL services (API first, wait for sync, then others)
./bin/start --ui-only    # Start only UIs (web, canvas, memory) - no sync
./bin/start --no-api     # Start services+UIs without API (skip sync wait)
./bin/start --list       # Show all session status with health checks
./bin/start --stop       # Stop all Jarvis tmux sessions

tmux attach -t jarvis-web
tmux attach -t jarvis-memory
# etc.

start and use as needed
./bin/jarvis-dashboard ( jarvis-d shortcut in cli)

cloud or local  both to get all tables made and to create embedding for tools and mcp tools
 ./bin/sync_tools.py cloud
 ./bin/sync_tools.py local

# trigger reflection manually
python3 -c "from lib.intelligence_hooks import trigger_reflection; trigger_reflection(10)"
curl -X POST "http://localhost:8880/api/intelligence/reflect?batch_size=5"
```

# Feedback Commands

## Usage Methods

### Method 1: `--feedback` Flag (Quick Debugging)

Add `--feedback` to any orchestrator command:

```bash
# Basic usage
./orchestrator/orchestrator_v2.py cloud "What time is it?" --feedback

# With other flags
./orchestrator/orchestrator_v2.py cloud "Search memory" --feedback --json
./orchestrator/orchestrator_v2.py cloud "Complex task" --feedback --debug-thinking



# Combine with other flags
./orchestrator/orchestrator_v2.py cloud "Research bitcoin" --speak --feedback
```

**When to use**: 
- Debugging a specific query
- Spot-checking after changes
- One-off testing

### Method 2: `bin/jarvis-feedback` (Dedicated Tool)

Standalone tool with multiple commands:

```bash
./bin/jarvis-feedback run "Query here"      # Single query with feedback
./bin/jarvis-feedback batch file.txt        # Batch testing
./bin/jarvis-feedback summary               # Summarize recent feedback
./bin/jarvis-feedback recent                # Show recent feedback entries
./bin/jarvis-feedback issues                # Show only issues (rating < 5)
```


# Evolution Commands

┌─────────────────────────────────────────────────────────────────┐
│                    EVOLUTION WORKFLOW (Manual)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  STEP 1: Collect Feedback (happens during normal use)           │
│  ──────────────────────────────────────────────────             │
│    ./orchestrator/orchestrator_v2.py cloud "query" --feedback   │
│    → Feedback LLM grades interaction (1-5 scale)                │
│    → Logged to logs/feedback/feedback-YYYY-MM-DD.jsonl          │
│                                                                 │
│  STEP 2: Check Evolution Candidates (run when you want)         │
│  ─────────────────────────────────────────────────────          │
│    ./bin/evolve-prompts check                                   │
│    → Shows components with low ratings                          │
│    → Ratings 1,2,3 count as "low" (need 2+ to trigger)          │
│                                                                 │
│  STEP 3: Generate Improvements (run for specific component)     │
│  ───────────────────────────────────────────────────────        │
│    ./bin/evolve-prompts generate tool:xyz                       │
│    → LLM generates improved description                         │
│    → Shows before/after comparison                              │
│                                                                 │
│  STEP 4: Review & Apply                                         │
│  ─────────────────────────                                      │
│    Tool descriptions:                                           │
│      ./bin/evolve-prompts generate tool:xyz --deploy --activate │
│      → Auto-updates tool.json file                              │
│                                                                 │
│    System prompt:                                                │
│      ./bin/evolve-prompts generate system_prompt --deploy       │
│      → Saves to logs/evolution/system_prompt_suggestions.md     │
│      → YOU manually apply to router_v2.py                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

```bash
# 1. Run queries with feedback collection
# Manual - per query
./orchestrator/orchestrator_v2.py cloud "Do something" --feedback

# 2. Check what needs evolution
./bin/evolve-prompts check

# 3. Generate & preview improvement
./bin/evolve-prompts generate tool:xyz

# 4. Deploy tool improvement
./bin/evolve-prompts generate tool:xyz --deploy --activate

# 5. Generate system prompt suggestions
./bin/evolve-prompts generate system_prompt --deploy

# 6. View system prompt suggestions
cat logs/evolution/system_prompt_suggestions.md

# Check what needs evolution (includes MCP status)
./bin/evolve-prompts check --show-mcp

# Auto-evolve (dry run)
./bin/evolve-prompts auto

# Auto-evolve (deploy but don't activate - for A/B testing) - NOT SETUP YET
./bin/evolve-prompts auto --deploy

# Auto-evolve (deploy AND activate immediately)
./bin/evolve-prompts auto --deploy --activate

# View evolution logs
cat logs/evolution/evolution-$(date +%Y-%m-%d).jsonl | jq '.'

Test evolution_test - Run queries with --feedback, accumulate low ratings
Watch logs - cat logs/evolution/evolution-$(date +%Y-%m-%d).jsonl | jq '.'
Run evolution - ./bin/evolve-prompts check to see candidates
Verify improvements - Compare before/after descriptions

## local
# After evolving prompts in cloud mode:
./bin/sync-evolution-db.py local --update-files
./bin/sync_tools.py local

# Or via dashboard:
jarvis-dashboard → 🧬 Evolution → Sync Evolution → Local

# CLI for system prompt suggestions
cat logs/evolution/system_prompt_suggestions.md

# Dashboard for system prompt suggestions
jarvis-dashboard → 🧬 Evolution → System Prompt Suggestions
---

# Tool builder commands

```bash
# Build a tool from a gap
./bin/build-tool --mode cloud build "Description of capability needed"

# List pending tools (need package approval)
./bin/build-tool list-pending

# Approve pending tool (with package install)
./bin/build-tool approve tool_name --install

# View tool report card
./bin/build-tool info tool_name

# Sync to enable
./bin/sync_tools.py cloud
```

# Self-Play Commands

```bash
# Quick test (5 queries)
./bin/jarvis-self-play --queries 5 --mode cloud

# Standard session with feedback
./bin/jarvis-self-play --queries 20 --mode cloud

# List past sessions
./bin/jarvis-self-play list

# View results
./bin/jarvis-self-play results --session latest

# Only information and media (safest)
./bin/jarvis-self-play --queries 10 --categories information media research

# Skip productivity if worried about memory writes
./bin/jarvis-self-play --queries 10 --categories information research media general

# Testing Commands

```bash

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

# Load a custom prompt (from jarvis-web/data/prompts/NAME.md)

```bash
./orchestrator/orchestrator_v2.py cloud "query" --prompt deep_research "Research AI chips"

# List available prompts (on error)
./orchestrator/orchestrator_v2.py cloud --prompt nonexistent "test"
# Shows: blog_post, code_review, compare, daily, debug, deep_research, email, explain...
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
# Manual sync between DBs
./bin/sync-memory-db.py --from local --to cloud  # Sync from local → cloud
./bin/sync-memory-db.py --from cloud --to local # Sync from cloud → local

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
./bin/run-intelligence-maintenance.py --anomaly
./bin/run-intelligence-maintenance.py --meta
# Normal run - will skip if already ran within 14 days
./bin/run-intelligence-maintenance.py --decay

# Force run - bypasses interval check (use with caution!)
./bin/run-intelligence-maintenance.py --decay --force

# All jobs
curl -X POST http://localhost:8880/api/intelligence/maintenance/all

# Individual
curl -X POST http://localhost:8880/api/intelligence/maintenance/decay
curl -X POST http://localhost:8880/api/intelligence/maintenance/anomaly
curl -X POST http://localhost:8880/api/intelligence/maintenance/meta-cognition

# View meta-knowledge
curl http://localhost:8880/api/intelligence/meta-knowledge

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

# Unify systemd
```bash
sudo systemctl status unifi-protect-webhook   # Check status
sudo journalctl -u unifi-protect-webhook -f   # View logs
sudo systemctl restart unifi-protect-webhook  # Restart
sudo systemctl stop unifi-protect-webhook     # Stop
```

# Spotify recommendations

```bash
You: "What music do you recommend for this evening?"
Jarvis: [Plays 20 tracks based on your taste - Tad, Primus, etc.]

You: "I want some chill music suggestions"  
Jarvis: "Here are some suggestions: 1. Best Chill Songs... Say 'play number X'"
```

# Test tool similarityu without actually running a tool

```bash
# Run all default test queries (full analysis)
./tests/test_tool_similarity.py

# Test a single query
./tests/test_tool_similarity.py "call my mom"
./tests/test_tool_similarity.py "play some jazz"

# Test with a specific threshold
./tests/test_tool_similarity.py --threshold 0.30

# Show ALL tools (not just top 10)
./tests/test_tool_similarity.py "build an api" --all

# Test local mode
./tests/test_tool_similarity.py --mode local
```

# Image gen tool

```bash
 ./orchestrator/orchestrator_v2.py cloud "Generate a black ford truck image"
```

# web

# add block tools
```bash
curl -X PUT http://localhost:5001/api/settings/blocked-tools \
  -H "Content-Type: application/json" \
  -d '{"blocked": ["get_recent_conversations", "some_other_tool"]}'
```

# Clean up intellegence db after testing and back or many pending reflections

```bash
cd /home/boss/jarvis-voice && python3 bin/cleanup-intelligence.py --dry-run

cd /home/boss/jarvis-voice && python3 bin/cleanup-intelligence.py --execute
```

# Memory Browser

```bash
./bin/jarvis-memory            # Runs on port 5002
./bin/jarvis-memory --port 5003 --debug  # Custom options
```

Standards to follow for tools ( required / action / optional )

┌─────────────────────────────────────────────────────────────────┐
│                    TOOL JSON REQUIRED RULES                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Multi-action tool (does many things)?                       │
│     → Add "action" enum param                                   │
│     → required: ["action"]                                      │
│                                                                 │
│  2. Single-purpose tool (does one thing)?                       │
│     → required = minimum params to function                     │
│     → e.g., search needs "query", bash needs "command"          │
│                                                                 │
│  3. Tool works with sensible defaults?                          │
│     → required: [] or omit entirely                             │
│     → e.g., get_time defaults to local time                     │
│                                                                 │
│  4. The "required" array should contain ONLY what the Python    │
│     script CANNOT work without.                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Action tools" = tools that DO/CHANGE something (vs tools that just READ/QUERY):
Action Tools (modify state)	Query Tools (read-only)
execute_bash - runs commands	search_memory - reads memories
remember - saves data	get_time - reads time
send_email - sends email	list_reminders - reads reminders
spotify (play/pause)	weather - reads weather
api_call - makes API requests	get_recent_conversations - reads logs
printer - prints documents	query_service_logs - reads logs

# Example of saving a stash artifact to memory
```bash
from memory_db import MemoryDB

# After stash save succeeds
db = MemoryDB()
db.remember(
    key=f"youtube_transcript_{space_id}",
    value=f"YouTube transcript: {video_title}. STASH: {md_ref}. FILE: {md_filename}. URL: {url}",
    category="stash_artifact",
    importance=6,
    source="youtube_transcript",
    metadata={
        "stash_ref": md_ref,
        "youtube_url": url,
        "video_title": video_title,
        "tags": ["transcript", "youtube", "video", "text"],
        "type": "transcript"
    }
)
```



./bin/build-tool --mode cloud build "Build a new tool called 'status_recap' that aggregates data from multiple existing Jarvis tools into a briefing summary.

PURPOSE: When user says 'give me a recap' or 'status briefing', call existing tools and compile results into a summary.

THIS TOOL SHOULD CALL THESE EXISTING TOOLS you should pick the best order to build summary and display on canvas:
- get_time: For greeting and time context
- weather: Current weather for Hillsboro, Oregon
- crypto_price: BTC, SOL prices with changes  
- list_alerts: Any active alerts
- list_reminders: Pending reminders
- system_monitor: Local system health
- generate_image: Generate a image of the current status weather, crypto prices, system health, alerts, reminders, etc.
- canvas: Create a canvas page with name and date in a folder called 'Daily Status' with the current status weather, crypto prices, system health, alerts, reminders, details and image of the current status.

Should use native provider grounding search as needed
Handle failures gracefully - if one tool fails, continue with others but show failure details on canvas.
more tools or features could be added to the tool later.


The tool should be resilient and time-aware (Good morning vs Good evening)."


./bin/build-tool --mode cloud build "Build a tool called 'status_recap' that gives me a comprehensive status briefing.

When I say 'give me a recap' or 'status update', this tool should:

1. GATHER DATA using these existing tools: ( use stash as needed so its saved in db with meta data and can be used for follow up questions )
   - get_time: Greeting based on time (Good morning/afternoon/evening) and current date
   - weather: Current weather for Hillsboro, Oregon
   - crypto_price: BTC and SOL prices with 24h change
   - list_alerts: Any active alerts
   - list_reminders: Pending reminders  
   - system_monitor: Local system CPU, memory, disk health

2. CREATE VISUAL OUTPUT:
   - generate_image: Create an image representing the current status (weather icon, crypto trends, system health indicators)
   - canvas: Save full report to a canvas page in 'Daily Status' folder, named with current date

3. SPEECH RESPONSE:
   - Brief summary of highlights for TTS
   - Mention anything urgent (alerts, low disk, big crypto moves)

EXTENSIBILITY:
- If user adds 'plus news' or 'with headlines', use native provider grounding search to add top news
- If user specifies different crypto like 'include ETH', add those to the check
- Tool should accept optional parameters to customize what sections to include
- future ideas to add on are email tool to email boss the image and small summary 

BEHAVIOR:
- Time-aware greetings
- If any tool fails, continue with others and note the failure on canvas
- Summarize don't overwhelm - canvas has details, speech has highlights"





The stash tool returns ref, not stash_ref: ??/  The stash_ref is at data.saved.stash_ref, not data.stash_ref. ??? 
I see all the issues now:
Image not embedded - Need ![title](stash://...) markdown format
Wrong data paths - system_monitor uses cpu.total_percent, memory.ram.percent_used, disks[0].percent_used
Crypto data paths wrong - Uses price_usd not price, change_24h_percent not change_24h
Reminders showing all - Need to filter for status: "scheduled" only


```bash
If tool is made need to update timeouts in executor.py

# Use longer timeout for local mode (Ollama can be slower)
            # OpenCode tasks need much more time (building, coding, etc.)
            # Ingest intel needs time for embedding generation (especially large profiles)
            if tool_name == "opencode":
                timeout = 360  # 6 minutes for OpenCode tasks (complex builds)
            elif tool_name == "ingest_intel":
                timeout = 180  # 3 minutes for ingesting files with embeddings (large profiles can have 300+ facts)
            elif tool_name == "manage_intel":
                timeout = 180  # 3 minutes (can auto-ingest, which needs time for embeddings)
            elif tool_name == "generate_image":
                timeout = 300  # 5 minutes for AI image generation (especially with grounding)
            elif tool_name == "generate_music":
                timeout = 600  # 10 minutes for music generation (can take 3-5min for longer tracks)
            elif tool_name == "weather":
                timeout = 30  # Weather API can be slow with proxy fallback
            elif tool_name == "status_recap":
                timeout = 180  # 3 minutes - calls multiple tools including generate_image
            else:
                timeout = 60 if self.mode == "local" else 45  # Increased default (was 30/15)
```

```bash
# Basic validation
./bin/validate-system-prompt --tools

# Focus on a specific area
./bin/validate-system-prompt --tools --focus "canvas workflow"

# Simulate a task and check for issues
./bin/validate-system-prompt --tools --simulate "research wifi cameras and save to canvas"

# Compare to previous validation (track improvements)
./bin/validate-system-prompt --tools --compare

# Dry run - see what the validator sees
./bin/validate-system-prompt --tools --dry-run

# Use xAI instead of Anthropic
./bin/validate-system-prompt --tools --provider xai

# Save full prompt in log
./bin/validate-system-prompt --tools --full-prompt


# Debug specific observed behavior
./bin/validate-system-prompt --tools --provider xai --issue "Jarvis used canvas first, then mcp brave search twice, then canvas again - only last canvas had data"

# Combine with focus for even more targeted analysis
./bin/validate-system-prompt --tools --issue "search_memory called 3 times in a row for same query" --focus memory

# Dry run to see what will be analyzed
./bin/validate-system-prompt --tools --issue "Jarvis stopped responding after list_reminders" --dry-run
```

```bash
TODAY=$(date +%Y-%m-%d)

# Watch external requests live
tail -f logs/api/access-$TODAY.jsonl | jq .

# Count by endpoint
cat logs/api/access-$TODAY.jsonl | jq -r '.path' | sort | uniq -c | sort -rn

# Show Samantha requests (Tailscale 100.x)
cat logs/api/access-$TODAY.jsonl | jq 'select(.client_ip | startswith("100."))'

# View errors with request body
cat logs/api/errors-$TODAY.jsonl | jq '{timestamp, path, status, request_body}'

# Slow requests (>100ms)
cat logs/api/access-$TODAY.jsonl | jq 'select(.duration_ms > 100)'

# Preview what would be deleted
./bin/cleanup-logs --dry-run

# Delete logs older than 60 days (default)
./bin/cleanup-logs

# Custom retention
./bin/cleanup-logs --days 30


Workflow when docs change:

qmd update      # re-index changed files
qmd embed       # regenerate embeddings (if needed)
qmd status      # verify everything is working
```




# Price Alert Monitor - adding new assets

1. Edit config/price-alerts.yaml     → Add symbol + conditions
2. In n8n: Copy a Fetch node         → Change URL to new symbol
3. Wire to Wait For All Data         → Increase numberInputs
4. In Code node: Add identification  → if (symbol === 'NEW') newData = json.data;
5. In Code node: Add threshold check → Copy existing block, change symbol


#	Fix	File
1	SSRF protection	api_call.py
2	js_code allowlist	crawl_url.py
3	Command blocklist + protected paths	execute_bash.py
4	Injection detection	remember.py
5	Input sanitization	orchestrator_v2.py
6	SSRF protection	screenshot_url.py
7	SSRF for direct URLs	send_webhook.py
8	File path restrictions	analyze_image.py
9	File path restrictions	pdf_read.py
10	Vision prompt sanitization	analyze_image.py


