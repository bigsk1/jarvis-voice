# Jarvis Background Services - Documentation

Proactive assistant services that run 24/7 to manage alerts, auto-resolve issues, and send reminders.

---

## 📚 Documentation Index

### Architecture & Design
- **[Proactive Assistant System](PROACTIVE_ASSISTANT_SYSTEM.md)** - Complete system architecture
- **[Phase 1 Complete](PHASE_1_COMPLETE.md)** - Alert system implementation details
- **[Service Architecture FAQ](SERVICE_ARCHITECTURE_FAQ.md)** - How services work, concurrency, safety

### Service Details
- **[Service Logging](SERVICE_LOGGING.md)** - Structured logging system
- **[Fixes](FIXES.md)** - Service-related fixes

---

## Services Overview

### 1. Follow-Up Daemon
Re-notifies about unacknowledged alerts

**Intervals:**
- First: 10 minutes
- Second: 30 minutes  
- Third: 60 minutes
- Max: 3 follow-ups

### 2. Self-Healing Daemon
Auto-resolves alerts by checking URLs

**Features:**
- Checks URLs every 60 seconds
- Auto-resolves when service responds
- TTS notification on recovery

### 3. Reminder Scheduler
Triggers time-based reminders

**Features:**
- Checks every 60 seconds
- Executes callback when time reached
- Marks reminders as completed

---

## Management

### Start All Services
```bash
./bin/jarvis-services
```

### Restart Services
```bash
./bin/restart-services
```

### Check Logs
```bash
tail -f logs/services/self_healing_daemon-$(date +%Y-%m-%d).log
tail -f logs/services/follow_up_daemon-$(date +%Y-%m-%d).log
tail -f logs/services/reminder_scheduler-$(date +%Y-%m-%d).log
```

### Query Service Status
```
"Hey Jarvis, query service logs"
```

---

## Key Features

✅ **No LLM Calls** - Services don't make expensive API calls
✅ **TTS Only** - Uses say.sh/say-local.sh for notifications (~$0.015/1K chars)
✅ **Safety Limits** - MAX_FOLLOW_UPS, MAX_CHECKS_PER_LOOP built-in
✅ **Structured Logging** - JSON + text logs for debugging
✅ **Jarvis Awareness** - Can query logs via `query_service_logs` tool
✅ **Independent** - Runs separately from API and wake word

---

## Quick Links

**Start Here**: [Proactive Assistant System](PROACTIVE_ASSISTANT_SYSTEM.md)

**How It Works**: [Service Architecture FAQ](SERVICE_ARCHITECTURE_FAQ.md)

**API Integration**: [docs/api/](../api/)

