# Jarvis Reminder System

## Overview

Jarvis supports **three ways** to create reminders:

1. **Voice (Natural Language)** - "Remind me in 4 hours..."
2. **API (Programmatic)** - POST `/api/reminders` with UTC time
3. **Intel Files (Context)** - Store details, query with `semantic_recall`

---

## 1. Voice Reminders (Recommended)

Use natural language with Jarvis:

```
"Remind me in 30 minutes to check the oven"
"Remind me tomorrow at 3pm to call mom"
"Remind me every Wednesday to take out trash"
"Remind me every month on the 10th about Netflix bill"
"Remind me on the 15th to submit report"
```

### Supported Time Expressions

**Relative:**
- "in X minutes" → `in 30 minutes`
- "in X hours" → `in 4 hours`
- "in X days" → `in 2 days`
- Compound: "in 1 hour 30 minutes"

**Absolute:**
- "tomorrow at 3pm"
- "at 5pm" (today if not passed, else tomorrow)
- "on the 15th" (defaults to 10am)

**Recurring:**
- "every Monday" → Weekly, 10am default
- "every Friday at 5pm" → Weekly with custom time
- "every month on the 10th" → Monthly, 10am default
- "every month on the 15th at 9am" → Monthly with custom time

### Default Time

If no time specified, **10am** is used:
- "Remind me on the 15th" → 15th at 10:00 AM
- "Remind me every Wednesday" → Every Wed at 10:00 AM
- "Remind me tomorrow" → Tomorrow at 10:00 AM

### Recurrence Rules

Behind the scenes, these are stored as:
- `WEEKLY:0` = Monday, `WEEKLY:1` = Tuesday, ... `WEEKLY:6` = Sunday
- `MONTHLY:10` = 10th of each month, `MONTHLY:15` = 15th, etc.

---

## 2. API Reminders (External Systems)

For calendar sync, automation, or external apps:

### Create Reminder

```bash
POST http://localhost:8880/api/reminders
Content-Type: application/json

{
  "title": "Team Meeting",                    # Required
  "description": "Weekly standup",            # Optional
  "trigger_time": "2025-11-24T15:00:00",     # Required (UTC!)
  "related_intel_file": "meeting-notes.md",  # Optional
  "callback_url": "https://...",             # Optional
  "metadata": {"calendar_id": "evt_123"}     # Optional
}
```

**Important**: `trigger_time` must be **UTC in ISO 8601 format**.

### List Reminders

```bash
# All reminders
GET /api/reminders

# Only scheduled (upcoming)
GET /api/reminders?status=scheduled

# Only triggered (fired, not acknowledged)
GET /api/reminders?status=triggered

# Only acknowledged (completed)
GET /api/reminders?status=acknowledged
```

### Acknowledge Reminder

```bash
POST /api/reminders/{id}/acknowledge
```

### Delete Reminder

```bash
DELETE /api/reminders/{id}
```

---

## 3. Intel Files (Contextual Knowledge)

Intel files provide **context** for Jarvis, not automatic reminders.

### Example: Netflix Subscription

Create `jarvis-intel/netflix.md`:
```markdown
# Netflix Subscription

**Bill Date**: 10th of every month
**Amount**: $15.99
**Card**: Ending in 1234
**Plan**: Premium (4 screens)
**Cancel Link**: https://netflix.com/cancel

## Notes
- Auto-renews on 10th
- Can downgrade to Standard ($10.99)
- Watch for price increases
```

### Ingest Into Knowledge Base

```bash
# Option 1: Voice
"Hey Jarvis, ingest all intel files"

# Option 2: Tool directly
echo '{"action": "ingest"}' | python3 skills/ingest_intel.py
```

### How Jarvis Uses Intel

When you ask relevant questions:
```
You: "When is my Netflix bill due?"
Jarvis: (Uses semantic_recall) "Your Netflix bill is due on the 10th of every month."

You: "How much is Netflix?"
Jarvis: "Your Netflix Premium plan is $15.99."
```

### Intel vs Reminders

| Feature | Intel Files | Reminders |
|---------|-------------|-----------|
| **Purpose** | Contextual knowledge | Time-based alerts |
| **How Used** | Semantic search (questions) | TTS at trigger time |
| **Proactive?** | No (only when relevant) | Yes (speaks when due) |
| **Storage** | `knowledge_base` table | `reminders` table |
| **Example** | "What's my server IP?" | "Submit timesheet every Friday" |

**Linking Them**:
- Create reminder with `related_intel_file: "netflix.md"`
- When reminder triggers, Jarvis can optionally reference the intel for context
- Currently manual, could be automated in future

---

## Voice Tool Usage

### Create Reminder
```bash
./jarvis-local "Remind me in 4 hours to check dinner"
./jarvis-local "Remind me every Wednesday to take out trash"
```

### List Reminders
```bash
./jarvis-local "What reminders do I have?"
./jarvis-local "Show me scheduled reminders"
```

### Acknowledge Reminders

**Via Voice:**
```bash
./jarvis-local "Clear all my reminders"          # Clears ALL (scheduled + triggered)
./jarvis-local "Clear reminder 5"                # Clear specific ID
./jarvis-local "Acknowledge reminder 11 and 12"  # Clear multiple IDs
./jarvis-local "Mark my Netflix reminder as done" # By title (fuzzy match)
```

**Via API:**
```bash
# Acknowledge all pending reminders
curl -X POST http://localhost:8880/api/reminders/acknowledge-all

# Acknowledge specific reminder by ID
curl -X POST http://localhost:8880/api/reminders/11/acknowledge

# Or using the tool directly (for testing)
echo '{"reminder_ids": [11, 12]}' | python3 skills/acknowledge_reminders.py
echo '{"all_triggered": true}' | python3 skills/acknowledge_reminders.py
```

**Important:** Acknowledging a recurring reminder **stops it from recurring**. If you want it to continue, just let it auto-reschedule after triggering.

---

## Calendar Integration Example

Sync Google Calendar events to Jarvis:

```python
#!/usr/bin/env python3
# sync-calendar.py
import requests
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Google Calendar setup
creds = Credentials.from_authorized_user_file('token.json')
service = build('calendar', 'v3', credentials=creds)

# Get upcoming events
now = datetime.now(timezone.utc).isoformat()
events = service.events().list(
    calendarId='primary',
    timeMin=now,
    maxResults=10,
    singleEvents=True,
    orderBy='startTime'
).execute()

# Sync to Jarvis
for event in events.get('items', []):
    start = event['start'].get('dateTime', event['start'].get('date'))
    
    # Create reminder in Jarvis
    response = requests.post(
        'http://localhost:8880/api/reminders',
        json={
            'title': event['summary'],
            'description': event.get('description', ''),
            'trigger_time': start,
            'metadata': {
                'calendar_id': event['id'],
                'source': 'google_calendar'
            }
        }
    )
    
    if response.ok:
        print(f"✓ Synced: {event['summary']}")
    else:
        print(f"✗ Failed: {event['summary']}")
```

Run with cron:
```bash
# Sync every hour
0 * * * * /home/boss/jarvis-voice/sync-calendar.py
```

---

## Reminder Lifecycle

1. **Created** → `status = 'scheduled'`
2. **Time arrives** → `reminder_scheduler` daemon detects
3. **Triggered** → `status = 'triggered'`, Jarvis speaks via TTS
4. **Acknowledged** → `status = 'acknowledged'` (manual or voice)

### For Recurring Reminders

1. Trigger occurs → Speaks TTS notification
2. **Auto-reschedules** → Status stays `'scheduled'`, `trigger_time` updated to next occurrence
3. Repeats forever until deleted or acknowledged

**Example Flow:**
```
1. Create: "Remind me every Wednesday to take out trash"
2. Wednesday 10am: Jarvis speaks → Auto-reschedules to next Wednesday
3. Next Wednesday 10am: Jarvis speaks → Auto-reschedules again
4. Continues indefinitely...
```

**Rescheduling Logic:**
- **Weekly**: Adds 7 days from current trigger
- **Monthly**: Moves to same day next month (handles edge cases like Feb 30)

**TTS Message:**
- One-time: "Boss, reminder: [title]. [description]"
- Recurring: "Boss, reminder: [title]. [description]. This is a weekly reminder, rescheduled for next Wednesday."

---

## Database Schema

```sql
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    trigger_time TIMESTAMP NOT NULL,  -- UTC
    status TEXT DEFAULT 'scheduled',  -- scheduled|triggered|acknowledged
    created_at TIMESTAMP,
    triggered_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    spoken BOOLEAN DEFAULT 0,
    spoken_at TIMESTAMP,
    related_intel_file TEXT,          -- Link to jarvis-intel/file.md
    callback_url TEXT,                -- Webhook to call on trigger
    recurrence_rule TEXT,             -- WEEKLY:2 or MONTHLY:10
    metadata TEXT                     -- JSON data
);
```

---

## Troubleshooting

### Reminder not triggering

1. Check reminder exists and is scheduled:
```bash
curl http://localhost:8880/api/reminders?status=scheduled | jq
```

2. Check trigger time is in the past (UTC):
```bash
sqlite3 data/jarvis_memory.db "SELECT id, title, trigger_time, datetime('now') FROM reminders WHERE id=X;"
```

3. Check reminder_scheduler is running:
```bash
ps aux | grep reminder_scheduler
tail -f logs/services/reminder_scheduler-$(date +%Y-%m-%d).log
```

4. Restart services:
```bash
./bin/restart-services
```

### Wrong time zone

API requires **UTC time**. Convert local to UTC:

```python
from datetime import datetime, timezone

# Local time
local_time = datetime(2025, 11, 24, 10, 0)  # 10am local

# Convert to UTC
utc_time = local_time.astimezone(timezone.utc)
print(utc_time.isoformat())  # Use this for trigger_time
```

### Recurring reminders not re-triggering

**This feature is now fully implemented!** ✅

Check these if reminders aren't re-triggering:

1. **Verify recurrence rule exists:**
```bash
sqlite3 data/jarvis_memory.db "SELECT id, title, recurrence_rule, trigger_time FROM reminders WHERE id=X;"
```

2. **Check scheduler logs:**
```bash
tail -f logs/services/reminder_scheduler-$(date +%Y-%m-%d).log
```

3. **Manually test calculation:**
```python
from datetime import datetime, timedelta

# Weekly test
current = datetime.fromisoformat('2025-11-18T10:00:00')
next_trigger = current + timedelta(days=7)
print(f"Next weekly: {next_trigger}")

# Monthly test
next_month = current.replace(month=current.month + 1) if current.month < 12 else current.replace(year=current.year + 1, month=1)
print(f"Next monthly: {next_month}")
```

4. **Check reminder wasn't accidentally acknowledged:**
```bash
sqlite3 data/jarvis_memory.db "SELECT status FROM reminders WHERE id=X;"
# Should be 'scheduled', not 'acknowledged'
```

---

## See Also

- API Quick Start: `docs/api/API_QUICK_START.md`
- API Overview: `docs/api/API_OVERVIEW.md`
- Intel System: `jarvis-intel/README.md`
