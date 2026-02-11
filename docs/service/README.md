# Jarvis Background Services - Documentation

Proactive assistant services that run 24/7 to manage alerts, auto-resolve issues, monitor systemd services, and send reminders.

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
- Critical/High: 15 min, 30 min, 60 min
- Medium: 30 min, 60 min, 120 min
- Low: 60 min, 180 min, 360 min
- Max: 3 follow-ups

### 2. Self-Healing Daemon
Auto-resolves alerts and monitors systemd services

**Alert Auto-Resolution:**
- Checks URLs every 60 seconds
- Auto-resolves when service responds
- TTS notification on recovery

**Systemd Service Monitoring:**
- Monitors: `unifi-protect-webhook`, `opencode-jarvis` (optional)
- 90 second grace period (avoids reboot false alarms)
- Automatic restart attempts on failure
- Verbal alerts: "Hey Boss, X has stopped. I'm attempting to restart it."
- Recovery notifications when service comes back

**Sibling Daemon Monitoring:**
- Monitors: `reminder_scheduler`, `follow_up_daemon`, `jarvis_api`
- 60 second grace period
- Auto-restart for daemons, notify-only for API
- Verbal alerts when down, recovery notifications when back up
- Single notification per event (not repeated)

### 3. Reminder Scheduler
Triggers time-based reminders

**Features:**
- Checks every 60 seconds
- Supports recurring reminders (daily, weekly, monthly)
- TTS notification when triggered
- Webhook callback support

---

## Resilience Features

All three daemons include database resilience (added January 2026):

| Feature | Description |
|---------|-------------|
| **Retry on DB Lock** | 5 retries with exponential backoff (1, 2, 4, 8, 16s) |
| **Connection Timeout** | 30 second SQLite timeout for locks |
| **Graceful Degradation** | Continues after transient errors instead of crashing |
| **Consecutive Error Limit** | Only exits after 10 consecutive failures |

This prevents daemons from crashing during database sync operations or heavy API usage.

---

## Watchdog (Cron)

The self-healing daemon monitors the other services, but nothing monitors
self-healing itself. A lightweight cron job fills that gap.

**Script:** `bin/watchdog-services.sh`

**Schedule:** Every 5 minutes via cron

```
*/5 * * * * /home/boss/jarvis-voice/bin/watchdog-services.sh >> /home/boss/jarvis-voice/logs/watchdog.log 2>&1
```

**Logic:**

| PID File | Process | Action |
|----------|---------|--------|
| Missing | — | Do nothing (intentional stop) |
| Exists | Alive | Do nothing (healthy) |
| Exists | Dead | Restart + TTS announce |

This design respects `jarvis-services --stop` which removes PID files.
Only unexpected crashes (stale PID file left behind) trigger a restart.

**Mode awareness:** `jarvis-services` writes the active mode (`cloud` or `local`)
to `logs/services_mode`. The watchdog reads this to source the correct env file
before restarting, so it works for both cloud and local deployments.

**Supervision chain:**
```
cron (5 min) → watchdog → self_healing_daemon → reminder_scheduler
                                               → follow_up_daemon
                                               → jarvis_api (notify only)
```

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

## Service & Daemon Monitoring

The self-healing daemon monitors two types of processes:

### 1. Systemd Services (external)

```python
# In services/self_healing_daemon.py
MONITORED_SYSTEMD_SERVICES = {
    "unifi-protect-webhook": {"required": True, "restart": False},
    "opencode-jarvis": {"required": False, "restart": False},  # Optional
}
SERVICE_GRACE_PERIOD = 90  # seconds before alerting
```

**Configuration Options:**
- `required: True` - Service must be installed, warns if missing
- `required: False` - Skip if not installed (for optional services)
- `restart: True` - Attempt automatic `systemctl restart` on failure

### 2. Sibling Daemons (PID-based)

Monitors the other daemons started by `bin/jarvis-services`:

```python
MONITORED_DAEMONS = {
    "reminder_scheduler": {
        "pid_file": "logs/reminder_scheduler.pid",
        "script": "reminder_scheduler.py",
        "restart": True,
    },
    "follow_up_daemon": {
        "pid_file": "logs/follow_up_daemon.pid",
        "script": "follow_up_daemon.py",
        "restart": True,
    },
    "jarvis_api": {
        "pid_file": "logs/jarvis-api.pid",
        "script": "server.py",
        "restart": False,       # Do NOT auto-restart
        "notify_only": True,    # Just speak notification
    },
    # Note: Don't monitor self_healing_daemon - that's us!
}
DAEMON_GRACE_PERIOD = 60  # seconds before alerting
```

**Configuration Options:**
- `restart: True` - Attempt automatic restart on failure
- `restart: False` - Don't auto-restart (manual intervention required)
- `notify_only: True` - Only speak notification, no restart attempt (e.g., for the API)

**How PID monitoring works:**
1. Reads PID from file (e.g., `logs/reminder_scheduler.pid`)
2. Checks if process exists (`kill -0 PID`)
3. Verifies it's the RIGHT process by checking `/proc/PID/cmdline` contains the script name
4. This prevents false positives from PID reuse

**Notification Behavior:**
- Notifications are sent **once** when a daemon goes down (after grace period)
- A recovery notification is sent **once** when it comes back up
- No repeated alerts - won't keep notifying every 60 seconds

**To add monitoring**, edit the appropriate dict and restart jarvis-services.

---

## Key Features

✅ **No LLM Calls** - Services don't make expensive API calls
✅ **TTS Only** - Uses say.sh/say-local.sh for notifications (~$0.015/1K chars)
✅ **Safety Limits** - MAX_FOLLOW_UPS, MAX_CHECKS_PER_LOOP built-in
✅ **Database Resilience** - Retry logic prevents crashes on DB locks
✅ **Service Monitoring** - Watches and auto-restarts critical systemd services
✅ **Structured Logging** - JSON + text logs for debugging
✅ **Jarvis Awareness** - Can query logs via `query_service_logs` tool
✅ **Independent** - Runs separately from API and wake word
✅ **Watchdog Cron** - Self-healing daemon auto-restarted if it crashes

---

## Log Management

All logs are stored in `logs/` with date-based filenames. **Default retention is 60 days.**

### Log Directories

| Directory | Contents | Size Range |
|-----------|----------|------------|
| `logs/` | LLM calls, workflows, baseline data | ~3MB/day (heavy use) |
| `logs/api/` | API request logs (external only) | ~50KB/day |
| `logs/services/` | Daemon logs (reminder, follow-up, self-healing) | ~500KB/day |
| `logs/intelligence/` | Intelligence engine logs | Varies |
| `logs/tools/` | Tool execution logs | Varies |
| `logs/opencode/` | OpenCode session logs | Varies |

### Cleanup Script

```bash
# Preview what would be deleted (dry run)
./bin/cleanup-logs --dry-run

# Delete logs older than 60 days (default)
./bin/cleanup-logs

# Custom retention (e.g., 30 days)
./bin/cleanup-logs --days 30
```

### Quick Commands

```bash
# Check total log size
du -sh logs/

# Check by subdirectory
du -sh logs/*

# Count log files
find logs -type f -name "*.log" -o -name "*.jsonl" | wc -l

# Find large log files (>10MB)
find logs -type f -size +10M

# Oldest log files
find logs -type f -name "*.jsonl" -printf '%T+ %p\n' | sort | head -10
```

### Automated Cleanup (Active)

Weekly cleanup runs every Sunday at 3am via cron:

```bash
# Current crontab entry:
0 3 * * 0 /home/boss/jarvis-voice/bin/cleanup-all >> /home/boss/jarvis-voice/logs/cleanup.log 2>&1
```

### Master Cleanup Script

The `cleanup-all` script handles everything with appropriate retention:

```bash
# Run all cleanups
./bin/cleanup-all

# Preview what would be deleted
./bin/cleanup-all --dry-run
```

**Retention periods:**

| Directory | Retention | Purpose |
|-----------|-----------|---------|
| `logs/` | 60 days | LLM calls, services, API, tools |
| `audio/` | 30 days | TTS output, mic recordings |
| `data/generated_images/` | 90 days | AI-generated images |
| `data/stash/` | 7 days (TTL) | Workflow artifacts, temporary storage |

### Individual Cleanup Scripts

```bash
# Logs only
./bin/cleanup-logs [--days N] [--dry-run]

# Audio only
./bin/cleanup-audio [--days N] [--dry-run]
```

### Stash vs Generated Images

```
generate_image tool
       │
       ├──► data/generated_images/   ← Long-term backup (90 days)
       │
       └──► data/stash/              ← Active workflows (7 days TTL)
                                       Canvas uses stash:// refs
```

- **Stash** = short-term, for active workflows and canvas references
- **Generated Images** = longer-term backup if you need to re-reference
- Memory stores `stash://` refs; if expired, LLM knows artifact is gone

### Files NOT Cleaned

The cleanup script preserves:
- `logs/*.pid` - PID files for running daemons
- `logs/baseline-*.json` - Token baseline reference data
- `logs/test/` - Test logs (manually managed)

---

## API Request Logging

See [API Logging Documentation](../api/LOGGING.md) for detailed API request logging:
- Log format and fields
- `jq` analysis commands
- Error investigation
- Configuration options

---

## Quick Links

**Start Here**: [Proactive Assistant System](PROACTIVE_ASSISTANT_SYSTEM.md)

**How It Works**: [Service Architecture FAQ](SERVICE_ARCHITECTURE_FAQ.md)

**API Integration**: [docs/api/](../api/)

---

*Last Updated: January 2026*

