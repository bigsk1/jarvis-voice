# Service Logging System

## Overview

Background services (follow-up daemon, self-healing daemon, reminder scheduler) now log all actions, errors, and events to **structured JSON logs** that Jarvis can query and monitor.

---

## Log Location

```
logs/services/
├── follow_up_daemon-2025-11-18.jsonl         # JSON logs
├── follow_up_daemon-2025-11-18.log           # Human-readable logs
├── self_healing_daemon-2025-11-18.jsonl
├── self_healing_daemon-2025-11-18.log
├── reminder_scheduler-2025-11-18.jsonl
└── reminder_scheduler-2025-11-18.log
```

- **`.jsonl`** files: Structured JSON (one JSON object per line) - Machine-readable
- **`.log`** files: Human-readable text logs with timestamps

Both are created automatically when services start. Logs rotate daily.

---

## What Gets Logged

### Event Types

| Event | Description | Example |
|-------|-------------|---------|
| `startup` | Service started | Mode, database path, config |
| `action` | Service performed an action | Follow-up sent, alert auto-resolved, reminder triggered |
| `error` | Error occurred | Failed to speak alert, URL check timeout |
| `check` | Periodic check completed | Found 2 pending alerts |
| `shutdown` | Service stopped | Total actions performed, errors |

### Log Entry Format

```json
{
  "timestamp": "2025-11-18T14:30:45.123456",
  "service": "follow_up_daemon",
  "event": "action",
  "action": "follow_up",
  "success": true,
  "details": {
    "alert_id": 5,
    "title": "Server Down",
    "severity": "high",
    "follow_up_count": 2
  }
}
```

---

## Querying Logs via Voice

Jarvis can now query service logs! Use the `query_service_logs` tool:

### Examples

**Check for errors:**
```
"Hey Jarvis, show me service errors"
→ Queries all services for error events
→ "Found 2 error entries. Latest error: Connection timeout for alert 3"
```

**Check specific service:**
```
"Hey Jarvis, what has the self-healing daemon done?"
→ Queries self_healing_daemon recent actions
→ "Found 12 log entries for self healing. 8 actions logged. Latest: url_check"
```

**Get statistics:**
```
"Hey Jarvis, show me service statistics"
→ Returns stats for all services
→ "Service statistics: 45 total actions, 1 error. Follow up: 12 actions. Self healing: 28 actions (1 error). Reminder: 5 actions."
```

**Check if services are running okay:**
```
"Hey Jarvis, are the background services running okay?"
→ Checks for recent errors and actions
→ "Found 18 log entries across all services. All services operational, no errors."
```

---

## Querying Logs Programmatically

### Via Tool (Recommended)

```bash
# Get recent logs from all services
echo '{"service": "all", "limit": 20}' | python3 skills/query_service_logs.py

# Get errors only from follow-up daemon
echo '{"service": "follow_up", "event_type": "error", "limit": 10}' | python3 skills/query_service_logs.py

# Get statistics
echo '{"service": "all", "show_stats": true}' | python3 skills/query_service_logs.py
```

### Via Python Library

```python
from service_logger import ServiceLogger

# Initialize logger
logger = ServiceLogger('follow_up_daemon')

# Get recent logs
recent = logger.get_recent_logs(limit=20)

# Get error logs only
errors = logger.get_error_logs(limit=10)

# Get statistics
stats = logger.get_stats()
print(f"Total actions: {stats['total_actions']}")
print(f"Total errors: {stats['total_errors']}")
print(f"Actions breakdown: {stats['actions']}")
```

---

## Log Statistics

The logger tracks:

- **Total actions** - Number of service actions performed
- **Successful actions** - Actions that completed successfully
- **Failed actions** - Actions that failed
- **Total errors** - Number of errors logged
- **Last error** - Most recent error with timestamp
- **Action breakdown** - Per-action type statistics

Example stats:

```json
{
  "service": "self_healing_daemon",
  "total_actions": 28,
  "successful_actions": 27,
  "failed_actions": 1,
  "total_errors": 1,
  "actions": {
    "url_check": {
      "count": 20,
      "success": 19,
      "failed": 1
    },
    "auto_resolve": {
      "count": 8,
      "success": 8,
      "failed": 0
    }
  },
  "last_error": {
    "timestamp": "2025-11-18T14:45:30.123456",
    "error": "Connection timeout for alert 3"
  }
}
```

---

## Viewing Logs Manually

### JSON Logs (for parsing)

```bash
# View recent entries
tail -20 logs/services/follow_up_daemon-2025-11-18.jsonl

# Search for errors
grep '"event": "error"' logs/services/*-2025-11-18.jsonl

# Parse with jq
jq 'select(.event == "error")' logs/services/self_healing_daemon-2025-11-18.jsonl
```

### Human-Readable Logs

```bash
# Follow live logs
tail -f logs/services/follow_up_daemon-2025-11-18.log

# View all service logs
tail -f logs/services/*.log

# Search for keywords
grep "error\|failed" logs/services/*.log
```

---

## Service-Specific Log Details

### Follow-Up Daemon

**Logs:**
- `startup`: Config with follow-up schedule
- `check`: Number of pending alerts found
- `action: follow_up`: Alert re-notification sent
- `error`: Failed to speak or update alert
- `shutdown`: Total follow-ups sent

**Example:**
```
[14:30:45] Service started in cloud mode
[14:31:45] Check: Found 2 item(s)
[14:31:45] Follow-up #1 for alert 5: Server Down
[14:46:45] Follow-up #2 for alert 5: Server Down
```

### Self-Healing Daemon

**Logs:**
- `startup`: Config with check limits and timeouts
- `check`: Number of alerts with auto_resolve_url
- `action: url_check`: URL check result (success/fail)
- `action: auto_resolve`: Alert auto-resolved
- `error`: URL check failed, network timeout
- `shutdown`: Total alerts resolved

**Example:**
```
[14:30:45] Service started in cloud mode
[14:35:45] Check: Found 3 item(s)
[14:35:45] URL check ✅ UP: https://example.com (alert 5)
[14:35:46] Auto-resolved alert 5: Server Down
```

### Reminder Scheduler

**Logs:**
- `startup`: Config with check interval
- `check`: Number of due reminders
- `action: trigger_reminder`: Reminder triggered
- `error`: Failed to trigger or callback failed
- `shutdown`: Total reminders triggered

**Example:**
```
[14:30:45] Service started in cloud mode
[15:00:00] Check: Found 1 item(s)
[15:00:00] Triggered reminder 12: Check Docker v29 in Coolify
```

---

## Jarvis Awareness

Jarvis can now **monitor his own services** and report on their health:

### Automatic Awareness

When services encounter errors, Jarvis can tell you:

```
"Hey Jarvis, did anything go wrong with the services?"
→ Checks error logs
→ "The self-healing daemon had 1 error: Connection timeout for alert 3. This happened at 2:45 PM."
```

### Proactive Awareness

You can ask Jarvis about service activity:

```
"Hey Jarvis, how many alerts were auto-resolved today?"
→ Queries self_healing_daemon action logs
→ "The self healing daemon auto-resolved 8 alerts today."

"Hey Jarvis, how many follow-ups have been sent?"
→ Queries follow_up_daemon stats
→ "The follow up daemon sent 12 follow-ups. Last follow-up was for 'Disk Space Low'."
```

---

## Error Handling

### Error Logging

All errors are logged with:
- Timestamp
- Error message
- Contextual details (alert_id, url, etc.)
- Service name

### Error Types

| Service | Common Errors | Logged Details |
|---------|---------------|----------------|
| Follow-up | TTS failure, DB update failed | alert_id, error message |
| Self-healing | URL timeout, connection refused | alert_id, url, status_code |
| Reminder | TTS failure, callback failed | reminder_id, callback_url |

### Recovery

Services continue running after errors:
- Errors are logged but don't crash the service
- Next check will retry
- Jarvis can be asked about failures

---

## Log Rotation

- Logs rotate **daily** (automatically by date in filename)
- Old logs are kept (no automatic deletion)
- You can manually archive/delete old logs:

```bash
# Archive logs older than 7 days
find logs/services -name "*.jsonl" -mtime +7 -exec gzip {} \;

# Delete logs older than 30 days
find logs/services -name "*.jsonl.gz" -mtime +30 -delete
```

---

## Best Practices

### For Monitoring

1. **Check errors periodically**: `"Hey Jarvis, show me service errors"`
2. **Review stats weekly**: `"Hey Jarvis, show me service statistics"`
3. **Watch for patterns**: Repeated errors might indicate a configuration issue

### For Debugging

1. **Check recent logs**: `tail -f logs/services/*.log`
2. **Filter by service**: Look at specific service JSON logs
3. **Use jq for analysis**: Parse JSON logs for patterns

### For Jarvis

1. **Ask about failures**: Jarvis is aware of errors
2. **Query specific actions**: "What did the self-healing daemon do?"
3. **Get summaries**: "Are the services running okay?"

---

## Summary

✅ **Structured Logging**: JSON logs for machine parsing
✅ **Human-Readable**: Text logs for quick viewing  
✅ **Jarvis Awareness**: Query logs via voice
✅ **Error Tracking**: All errors logged with context
✅ **Statistics**: Track service performance
✅ **Daily Rotation**: Automatic log file rotation
✅ **No Database Pollution**: Logs stay in files, not DB

Jarvis now has full visibility into background service operations! 🎯

