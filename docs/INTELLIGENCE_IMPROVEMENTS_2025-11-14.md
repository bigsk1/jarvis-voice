# Intelligence Improvements - November 14, 2025

## Problem Identified
Jarvis was not **intelligently auto-saving** valuable information after creating/building things. The system prompt said "proactively save" but only interpreted this as "when user shares information" - not when **Jarvis creates something**.

### Real-World Example
**Before:**
```
User: "Use OpenCode to build Flask API"
Jarvis: Builds API at ~/jarvis-workspace/projects/flask-hello-api on port 8080
Jarvis: Responds "Done!" 
Jarvis: Does NOT save location or run command
Result: Next time user says "start Flask API", Jarvis has no idea where it is
```

**This is the intelligence gap we fixed.**

---

## Solution: Enhanced System Prompt

### Added Clear Categories for Auto-Save

**A. USER SHARES information** (obvious cases):
- Personal info, preferences, contacts
- User explicitly provides data

**B. YOU CREATE/BUILD something** (CRITICAL - was missing):
- ✅ Project locations and run commands
- ✅ URLs, endpoints, ports you deployed
- ✅ Working solutions after troubleshooting
- ✅ File paths for projects you created

**C. YOU DISCOVER important facts** user might reference later:
- ✅ Significant events (market records, major news)
- ✅ Technical solutions that worked
- ✅ System configurations needed again

**D. DO NOT SAVE ephemeral data**:
- ❌ Current time (changes every second)
- ❌ Current prices (Bitcoin at $96k is noise unless requested)
- ❌ Temporary status checks

### Golden Rule Added
> "Ask yourself: Will the user benefit from this being saved for future reference? If YES → call 'remember'"

---

## Key Examples Added to System Prompt

### ✅ EXCELLENT Examples (What Intelligence Looks Like)

**Scenario 1: Port Conflict Resolution**
```
Deploy API on port 8000 → Port busy → Switch to 8091 → Works 
→ Call 'remember' with "api_name: port 8091, run: cd ~/path && node server.js"
```

**Scenario 2: Database Troubleshooting**
```
Troubleshoot database → Find working connection string
→ Call 'remember' with "db_connection: postgresql://localhost:5432/mydb worked after installing pg module"
```

**Scenario 3: Building Projects**
```
Build project with OpenCode → Build succeeds
→ Call 'remember' with project location, port, run command
→ Respond "Done"
```

### ❌ BAD Examples (What NOT to Do)

```
"What's Bitcoin price?" → Get $96k → Save it (NO! Ephemeral data, changes constantly)
Build project → Respond "Done" → Don't save location (NO! User will need this later)
```

---

## Additional Improvements

### 1. Port Selection Strategy
Added guidance to use **non-standard ports (8091+)** for OpenCode projects to avoid conflicts with commonly used ports (8080, 8000, 5000).

**Rationale**: Many services use standard ports. Starting at 8091+ reduces collision chances.

### 2. Database Schema Cleanup
- ✅ Removed unused `tool_patterns` table
- ✅ Removed unused `preferences` table  
- ✅ New databases only have: `knowledge_base` + `conversations`

### 3. New Conversation Tools
Created tools to access conversation history:
- `search_conversations` - keyword search across history
- `get_recent_conversations` - chronological list with session filtering

### 4. Metadata System Complete
- ✅ Memories store: source, timestamp, tool, creator
- ✅ Conversations store: model, tokens, cost, tool_count
- ✅ Full cost tracking per conversation

---

## Testing Needed

To verify the intelligence improvements work, test scenarios like:

### Test 1: Build & Recall
```bash
# Step 1: Build something
./orchestrator/orchestrator_v2.py cloud "Use OpenCode to create Express.js API on port 8091"

# Step 2: Check if location & run command were saved
sqlite3 data/jarvis_memory.db "SELECT key, value FROM knowledge_base WHERE key LIKE '%express%' OR key LIKE '%api%'"

# Step 3: Ask to start it (should use saved command)
./orchestrator/orchestrator_v2.py cloud "Start the Express API"
```

### Test 2: Ephemeral Data (Should NOT Save)
```bash
# Ask for current data
./orchestrator/orchestrator_v2.py cloud "What's the current time?"

# Verify it was NOT saved
sqlite3 data/jarvis_memory.db "SELECT COUNT(*) FROM knowledge_base WHERE value LIKE '%AM%' OR value LIKE '%PM%'"
# Should be 0 or very low
```

### Test 3: Troubleshooting Solution (Should Save)
```bash
# Simulate finding a solution
./orchestrator/orchestrator_v2.py cloud "The server won't start on port 8080, try 8091 instead"

# Check if the working solution was saved
sqlite3 data/jarvis_memory.db "SELECT key, value FROM knowledge_base WHERE value LIKE '%8091%'"
```

---

## Expected Behavior After Fix

### Scenario: OpenCode Project Creation

**User Request**: "Use OpenCode to build Flask API"

**Intelligent Flow**:
1. ✅ Call `opencode` tool with port 8091+ specification
2. ✅ OpenCode builds project at `~/jarvis-workspace/projects/flask-api-xyz`
3. ✅ **Auto-save to memory**:
   ```json
   {
     "category": "project",
     "key": "flask_api_location", 
     "value": "~/jarvis-workspace/projects/flask-api-xyz",
     "importance": 9
   }
   ```
4. ✅ **Auto-save run command**:
   ```json
   {
     "category": "project",
     "key": "flask_api_run_command",
     "value": "cd ~/jarvis-workspace/projects/flask-api-xyz && python3 app.py",
     "importance": 9
   }
   ```
5. ✅ **Auto-save port info**:
   ```json
   {
     "category": "project",
     "key": "flask_api_port",
     "value": "8091",
     "importance": 8
   }
   ```
6. ✅ Respond to user: "Flask API running on port 8091"

**Later...**

**User Request**: "Start the Flask API"

**Intelligent Recall**:
1. ✅ Call `search_memory` with query "flask api"
2. ✅ Find saved location + run command + port
3. ✅ Execute: `cd ~/jarvis-workspace/projects/flask-api-xyz && python3 app.py`
4. ✅ Respond: "Flask API started on port 8091"

**No guessing. No random searches. Pure intelligence.**

---

## Files Modified

1. `/home/boss/jarvis-voice/orchestrator/router_v2.py`
   - Enhanced system prompt with intelligent auto-save logic
   - Added clear categories (A/B/C/D) for when to save
   - Added diverse examples (not just "build Flask API" 5 times)
   - Added port selection strategy (8091+)

2. `/home/boss/jarvis-voice/lib/memory_db.py`
   - Removed zombie tables (`tool_patterns`, `preferences`)

3. `/home/boss/jarvis-voice/skills/search_conversations.py` (NEW)
   - Keyword search across conversation history

4. `/home/boss/jarvis-voice/skills/get_recent_conversations.py` (NEW)
   - Chronological conversation retrieval with session filtering

---

## Philosophy: Real Intelligence

**Dumb AI**: Responds correctly but forgets everything 5 seconds later.

**Smart AI**: 
- Recognizes patterns: "I just built something → user will need this later → save it"
- Filters noise: "Current Bitcoin price is ephemeral → don't save"
- Learns from actions: "Port conflict fixed by using 8091 → save this solution"
- Builds knowledge: Each task makes future tasks easier

**Goal**: Jarvis should get **smarter over time**, not start from zero every conversation.

---

## Success Metrics

After these changes, Jarvis should:
1. ✅ Auto-save project locations after OpenCode builds
2. ✅ Auto-save working solutions after troubleshooting
3. ✅ NOT save ephemeral data (time, current prices)
4. ✅ Use saved commands when asked to "start X"
5. ✅ Remember port assignments for projects
6. ✅ Track costs per conversation
7. ✅ Access previous conversation history

**The system is now INTELLIGENT, not just FUNCTIONAL.**

