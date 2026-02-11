# Service Architecture FAQ

## Understanding How Services Work (Safety & Cost Analysis)

---

## 🔥 Key Safety Points

### 1. **Services Do NOT Make LLM API Calls**

**CRITICAL**: Background services are **simple daemons**, not intelligent agents.

```python
# What services DOactually do:
while True:
    alerts = db.query("SELECT * FROM alerts")  # Local SQLite
    if alert_needs_followup:
        subprocess.run(["./bin/say.sh", message])  # TTS only
        db.update(alert)  # Local SQLite
    sleep(60)
```

**They do NOT:**
- ❌ Call Claude/GPT/Ollama
- ❌ Use tool calling system  
- ❌ Have intelligence/reasoning
- ❌ Search logs automatically
- ❌ Update intel automatically
- ❌ Loop trying to fix things

**They ONLY:**
- ✅ Query local database
- ✅ Call TTS (say.sh) when needed
- ✅ Make HTTP GET requests (self-healing checks)
- ✅ Update database records

### 2. **No Runaway API Costs**

**Maximum possible TTS costs:**

| Scenario | TTS Calls | Characters | Cost |
|----------|-----------|------------|------|
| 10 alerts, 3 follow-ups each | 30 | ~1,500 | $0.02 |
| 100 alerts, 3 follow-ups each | 300 | ~15,000 | $0.23 |
| Self-healing (100 resolves) | 100 | ~5,000 | $0.08 |

**OpenAI TTS Pricing**: $0.015 per 1K characters

**Safety Limits:**
```python
MAX_FOLLOW_UPS = 3        # Stop after 3 reminders
MAX_CHECKS_PER_LOOP = 10  # Only check 10 URLs per minute
```

---

## 🏗️ System Architecture

### Independent Processes

```
┌─────────────────────────────────────────────────────────┐
│  COMPLETELY INDEPENDENT (different PIDs, processes)     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  1. Wake Word (./jarvis)                PID: 10001     │
│     • Listens for "Hey Jarvis"                          │
│     • Calls orchestrator (DOES use LLM)                 │
│     • Tool limit: 10 per query                          │
│                                                          │
│  2. API Server (./bin/jarvis-api)       PID: 10002     │
│     • Receives webhooks                                  │
│     • Creates alerts in DB                              │
│     • Speaks urgent alerts (TTS only)                   │
│     • NO LLM calls                                      │
│                                                          │
│  3. Background Services                 PIDs: 10003-5   │
│     • Follow-up daemon         PID: 10003              │
│     • Self-healing daemon      PID: 10004              │
│     • Reminder scheduler       PID: 10005              │
│     • NO LLM calls                                      │
│     • TTS only when speaking                            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Independence = Resilience

**If API crashes:**
- ✅ Wake word keeps working
- ✅ Services keep working
- ❌ Can't receive new webhooks (but that's OK)

**If services crash:**
- ✅ Wake word keeps working
- ✅ API keeps working
- ✅ Watchdog cron restarts self-healing within 5 minutes
- ✅ Self-healing restarts reminder_scheduler and follow_up_daemon
- ❌ No follow-ups during the gap (but alerts still stored)

**If wake word crashes:**
- ✅ API keeps working
- ✅ Services keep working
- ❌ Can't voice control (restart with `./jarvis`)

---

## 🗣️ TTS (say.sh) Concurrent Usage

### No Conflicts!

Each TTS call is a **separate process**:

```bash
# These all run simultaneously without blocking:
./bin/say.sh "Alert 1" &  # PID 20001, exits after ~2 seconds
./bin/say.sh "Alert 2" &  # PID 20002, exits after ~2 seconds
./bin/say.sh "Alert 3" &  # PID 20003, exits after ~2 seconds
```

**How it works:**
1. Service calls `subprocess.run(["./bin/say.sh", message])`
2. New bash process spawned
3. TTS generates audio
4. Audio plays
5. Process exits
6. **No blocking, no conflicts**

**Multiple processes can speak at the same time** - your audio system mixes them.

---

## ⏰ How Reminders Work (Not Cron!)

### It's a Daemon, Not Cron

```python
# services/reminder_scheduler.py (simplified)
while True:
    now = datetime.now()
    
    # Query local database
    due_reminders = db.query("""
        SELECT * FROM reminders 
        WHERE status = 'scheduled' 
        AND trigger_time <= ?
    """, now)
    
    for reminder in due_reminders:
        speak(f"Reminder: {reminder.title}")  # TTS only
        db.update(reminder, status='triggered')
    
    sleep(60)  # Check every 60 seconds
```

**NOT cron-triggered!**
- Continuous loop (daemon)
- Checks every 60 seconds
- No external triggers
- Predictable behavior

---

## 📊 Tracking API Usage

### How to Know What Happened

**1. Service Logs (Structured JSON)**

```bash
# Count follow-up actions
jq 'select(.action == "follow_up")' logs/services/follow_up_daemon-2025-11-18.jsonl | wc -l

# Count TTS calls across all services
grep -E 'follow_up|trigger_reminder|auto_resolve' logs/services/*.jsonl | wc -l

# Get statistics
echo '{"service": "all", "show_stats": true}' | python3 skills/query_service_logs.py
```

**2. Ask Jarvis**

```
"Hey Jarvis, show me service statistics"
→ "45 actions total: 12 follow-ups, 28 URL checks, 5 reminders"

"Hey Jarvis, how many follow-ups were sent today?"
→ Counts action logs from follow_up_daemon
```

**3. Database Queries**

```sql
-- Count follow-ups sent
SELECT follow_up_count, COUNT(*) 
FROM alerts 
WHERE follow_up_count > 0 
GROUP BY follow_up_count;

-- Count triggered reminders
SELECT COUNT(*) 
FROM reminders 
WHERE status = 'triggered';
```

---

## 🛡️ Safety Mechanisms

### Built-In Limits

**Follow-Up Daemon:**
```python
MAX_FOLLOW_UPS = 3  # Stop after 3 reminders per alert
FOLLOW_UP_SCHEDULE = {
    "high": [15, 30, 60],  # Minutes between reminders
    "low": [60, 180, 360]
}
```

**Self-Healing Daemon:**
```python
MAX_CHECKS_PER_LOOP = 10  # Only check 10 URLs per minute
REQUEST_TIMEOUT = 10      # Timeout HTTP requests
```

**Reminder Scheduler:**
```python
# Reminders only trigger once (status changes to 'triggered')
# No loops, no retries
```

### Error Handling

**All services have try/except:**
```python
try:
    speak_alert(alert)
    log_action("follow_up", {...})
except Exception as e:
    log_error(f"TTS failed: {e}")
    # Continue running, don't crash
```

**Services never crash** - they log errors and continue.

---

## 💰 Cost Breakdown

### Service API Costs (Cloud Mode)

| Service | Action | API Call | Cost per Call | Frequency |
|---------|--------|----------|---------------|-----------|
| Follow-up | Speak reminder | OpenAI TTS | $0.015/1K chars | 3x per alert max |
| Self-healing | Speak resolution | OpenAI TTS | $0.015/1K chars | 1x per alert |
| Self-healing | Check URL | HTTP GET | Free | Every 5 min |
| Reminder | Speak reminder | OpenAI TTS | $0.015/1K chars | 1x per reminder |

**Example Monthly Costs (High Usage):**
- 200 alerts/month
- Each gets 2 follow-ups average = 400 TTS calls
- 50 chars average = 20K chars
- **Cost: $0.30/month** (30 cents)

**Voice Mode Costs (Separate):**
- LLM calls (Claude): ~$0.01-0.05 per query
- TTS (responses): ~$0.015/1K chars
- **This is WHERE costs come from, not services!**

---

## 🧪 Testing Cost/Usage Tracking

### Scenario: Run for 1 Day

```bash
# 1. Start services
./bin/jarvis-services

# 2. Create test alert
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "severity": "high", "source": "test"}'

# 3. Wait 24 hours

# 4. Check what happened
echo '{"service": "all", "show_stats": true}' | python3 skills/query_service_logs.py
```

**You'll see:**
```json
{
  "follow_up_daemon": {
    "total_actions": 3,  // 3 follow-ups sent
    "successful_actions": 3
  }
}
```

**Cost: 3 TTS calls × 50 chars = 150 chars = $0.002** (less than 1 cent)

---

## 📋 Alphabetical Tool Listing

**✅ IMPLEMENTED!** Tools now load in A-Z order:

```
✓ Registered tool: acknowledge_alerts
✓ Registered tool: api_call
✓ Registered tool: check_opencode_sessions
✓ Registered tool: check_tool_logs
✓ Registered tool: crypto_price
✓ Registered tool: execute_bash
✓ Registered tool: forget
✓ Registered tool: get_recent_conversations
✓ Registered tool: get_time
✓ Registered tool: ingest_intel
✓ Registered tool: list_alerts
✓ Registered tool: manage_intel
✓ Registered tool: opencode
✓ Registered tool: query_service_logs
✓ Registered tool: recall
✓ Registered tool: remember
✓ Registered tool: search_conversations
✓ Registered tool: search_memory
✓ Registered tool: semantic_recall
✓ Registered tool: send_webhook
✓ Registered tool: update_memory
```

Changed in `lib/tool_schema.py`:
- Local tools sorted alphabetically
- MCP tools sorted alphabetically

---

## ❓ Your Questions Answered

### Q: "Can services loop making 500 API calls?"

**A: No!** Services:
- Don't call LLMs (only TTS)
- Have MAX_FOLLOW_UPS = 3 limit
- Have MAX_CHECKS_PER_LOOP = 10 limit
- Only speak when actions trigger (not loops)

**Worst case:** 100 alerts × 3 follow-ups = 300 TTS calls = $0.45

### Q: "Do services have the 10 tool limit?"

**A: Services don't use tools at all!** 

Tool limit (10) only applies to:
- Voice mode: "Hey Jarvis, do X"
- API Q&A endpoint: `POST /api/voice/query`

Services are **not intelligent agents** - they're simple daemons.

### Q: "How do I know how many actions between starts/stops?"

**A: Check service logs!**

```bash
# Option 1: Service logs
jq 'select(.event == "shutdown")' logs/services/*-2025-11-18.jsonl

# Output:
{
  "event": "shutdown",
  "stats": {
    "total_follow_ups": 12,
    "checks": 1440  // 24 hours × 60 checks/hour
  }
}

# Option 2: Ask Jarvis
"Hey Jarvis, show me service statistics"
```

### Q: "What happens if self-healing daemon crashes?"

**A: The watchdog cron restarts it!**

A cron job (`bin/watchdog-services.sh`) runs every 5 minutes. If the self-healing
daemon's PID file exists but the process is dead, it restarts it and announces
via TTS: "Warning: self healing daemon crashed and has been restarted by watchdog."

```
Supervision chain:
  cron (5 min) → watchdog → self_healing_daemon → reminder_scheduler
                                                 → follow_up_daemon
                                                 → jarvis_api (notify only)
```

If you intentionally stop services with `jarvis-services --stop`, PID files are
removed, and the watchdog does nothing. Log: `logs/watchdog.log`

### Q: "Are there any edge cases of concern?"

**A: Only one edge case:**

**If you leave services running for months** with hundreds of pending alerts:
- Follow-up daemon speaks 3× per alert (max)
- **Solution**: Acknowledge old alerts periodically
- Or run: `curl -X POST http://localhost:8880/api/alerts/acknowledge-all`

**Not a concern:**
- Services won't loop infinitely
- Services won't call LLMs
- Services won't run up massive bills

---

## ✅ Summary

| Concern | Reality |
|---------|---------|
| Services make tons of LLM calls | ❌ Services don't call LLMs at all |
| Runaway API costs | ❌ TTS only, limited to 3× per alert |
| Services loop trying to fix things | ❌ Simple daemons, no intelligence |
| Can't track API usage | ✅ Structured logs track everything |
| say.sh conflicts when busy | ❌ Separate processes, no conflicts |
| Services crash if API down | ❌ Independent processes |
| Tool limit applies to services | ❌ Services don't use tools |
| Cron triggers cause problems | ❌ Daemons, not cron (cron only used for watchdog) |

**Your concerns are valid for voice mode (LLM calls), but services are simple and safe!** 🎯

---

## 🎯 Best Practices

1. **Monitor periodically**: `"Hey Jarvis, show me service statistics"`
2. **Check errors**: `"Hey Jarvis, show me service errors"`
3. **Acknowledge old alerts**: Prevents unnecessary follow-ups
4. **Review logs weekly**: `tail logs/services/*.log`
5. **Trust the limits**: MAX_FOLLOW_UPS prevents runaways

Services are **designed to be left running** - that's their purpose! 🚀

