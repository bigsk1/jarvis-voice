# Jarvis Reminder System

## Overview

Jarvis supports **two ways** to create reminders (intel files are related context, not reminders):

1. **Voice (Natural Language)** - "Remind me in 4 hours..."
2. **API (Programmatic)** - POST `/api/reminders` with UTC time

Intel files store durable context you can query with `semantic_recall`; they do **not** create time-based reminder triggers.

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

### Notification Time and Reminder Message

The `create_reminder` tool's `when` field is when Jarvis should notify the user.
Its `title` and `description` hold what to say, including any later appointment
time. For example, "Remind me tomorrow at noon about my appointment at 2pm"
requests **one notification at noon**, with the 2pm appointment retained in the
message. Use the explicitly requested notification time; do not calculate a
lead time or create an additional notification at the appointment time.

After saving that reminder, confirm the saved result. Additional reminders need
an explicit request for distinct notifications; repeating creation is not a way
to verify success or edit an existing reminder. Bounded daily schedules still
use one `create_reminder` call.

### Natural-language interpretation and validation

The existing conversation model can interpret varied wording into an optional
structured `schedule`; a shared resolver computes dates using one captured
reference time and the configured timezone. The model supplies selectors rather
than doing weekday/date arithmetic. For example:

```json
{
  "title": "Update firewall",
  "when": "Monday at 5pm",
  "schedule": {"kind": "weekday", "weekday": 0, "time": "17:00"}
}
```

`when` retains the original notification schedule. Supported selectors cover
elapsed delays, explicit dates, one-time weekdays, daily/weekly/monthly
recurrence, and bounded daily spans. There is no extra model request, service,
package, or database migration. Existing callers can continue supplying only
`when`; its parser must understand the complete expression rather than extract
one matching clock and ignore the remaining words.

Recognizable dates, weekdays, clocks and repetition constraints must agree with
the structured interpretation. Ambiguous or unsupported schedules require
clarification; the tool never intentionally approximates unsupported recurrence
or silently drops qualifiers. Invalid schedules return
`error_code: invalid_reminder_schedule` and `data.needs_clarification: true`
before opening the reminder database or calling Calendar. The spoken response
explains the problem and asks a specific clarification question, also returned
as `data.clarification_question`. It does not repeat a model's unverified claim
that a reminder was saved. All occurrences of a
bounded span are validated before any is saved, with a maximum of 366 dates.

Bare weekdays such as `Monday at 5pm` select the next upcoming occurrence,
including today if its time is still ahead. `next Monday` skips today when
today is Monday; `this Monday` also selects the upcoming occurrence, including
the coming Monday when requested on a weekend. Explicit past dates and impossible dates such
as February 30 are rejected. Month-end clamping remains limited to monthly
recurrence, where the original requested day remains in the recurrence rule.

Local times that fall inside a DST gap or ambiguous repeated hour require an
unambiguous time/offset; Jarvis does not silently move them or choose a fold.
An explicit ISO offset must agree with any accompanying natural-language
schedule. US standard/daylight abbreviations such as PST/PDT and EST/EDT denote
their fixed UTC offsets; they are not interchangeable across seasons. `Pacific`
or `PT` and `Eastern` or `ET` use the region's daylight-saving rules. Other
ambiguous abbreviations require an IANA zone or explicit UTC offset.
Calendar-day offsets preserve local wall
time; hour/minute delays are elapsed time. Infinite recurrence continues to use
the configured application timezone; a different zone requires clarification
rather than a silently incorrect recurring schedule.

The saved metadata and result retain the original schedule, reference time,
timezone and optional structured selectors. Confirmation independently compares
the actual tool arguments with returned times, recurrence and bounded sets at
that reference time. A proven mismatch adds a factual warning; it never creates
a replacement. Legacy receipts without a reference time remain readable.

The conversational orchestrator also checks an independently recognizable
notification clause in the original human request before executing the tool.
For example, if the request says `Monday at 5pm` but the model supplies only
`5pm`, a differing plan is rejected before any save or Calendar call. Appointment
times in the reminder message are not treated as extra notification times.
This is a bounded safeguard, not a second language model: wording that cannot
be independently resolved or associated with a particular reminder in a
multi-reminder request requires clarification when recognizable notification
constraints are present. Subject-first requests such as `remind me to update
the firewall at 5pm` retain their trailing notification clock. Conjoined
reminders retain separate subjects and schedules; an unfamiliar clause requires
clarification before saving rather than silently disappearing.

If `when` contains distinct times written with am/pm, noon/midday, midnight, or
24-hour clocks such as `14:00` (for example,
`October 23rd at noon about my appointment at 2pm`), creation fails before any
database access or Calendar sync. Retry with only the notification schedule in
`when`, retaining the appointment time in the message. Jarvis does not choose
between those times or save a reminder that then needs cancellation.
Equivalent clocks such as `noon`/`12pm` or `14:00`/`2pm` count as one time.
Clock minutes are preserved, including `tomorrow at 8:00am` and `tomorrow at
1:30pm`. A bare 12-hour clock such as `at five`, `5 o'clock` or `half past five`
requires AM/PM or an explicit daypart such as `in the evening`; a model-supplied
structured clock cannot replace the missing distinction. These hours and their
minutes are validated before fallback interpretation, so they cannot silently
become the default 10am. Colon clocks such as `17:00` use 24-hour notation.
Date numbers, occurrence counts and durations are not clock hours.

The existing `when` argument description explains bare-hour clarification,
dayparts and 24-hour clocks. The system prompt's current-date/time block and
versioned base instructions remain unchanged. Model-specific reminder overlays
also preserve explicitly requested timezones.

The system clock supplies the current instant; local interpretation and display
use the installation's configured `JARVIS_TIMEZONE` IANA zone. Non-US regions,
non-whole-hour offsets and their daylight-saving transitions use the same
validation. Stored trigger times remain UTC. There is no
`JARVIS_DEFAULT_TIMEZONE`/`JARVIS_DEFUALT_TIMEZONE` setting.

Other application paths retain their existing `America/Los_Angeles` fallback
when configuration is absent. Conversational reminders reject that implicit
fallback: ask the user for a timezone. A human-specified IANA zone or UTC can
supply a request-scoped timezone for a one-time or finite reminder; a model guess
cannot supply it. This does not modify the environment files. Recurrence requires
a persistent configured timezone because the scheduler uses the app setting.

Built-in reminders work without Google Workspace MCP or the legacy n8n Calendar
workflow. Calendar sync is optional and a sync failure does not invalidate the
saved local reminder.

These are routing instructions, not a semantic duplicate constraint. Exact
repeats can reuse an existing row, but different titles or notification times
can still create separate reminders. The conversational loop preserves explicit
requests for multiple reminders; it does not impose a one-reminder limit.

For requests consisting only of reminder creation, conversational confirmation
includes saved receipts and failures that remain uncorrected as complete
sentences. A schedule rejected before any write has
`error_code: invalid_reminder_schedule`; if a later successful retry keeps the
same title and description, its obsolete validation failure stays in the trace
without being spoken. Uncertain write failures and failures for other subjects
remain audible. Preparatory `tool_search`, `get_time`, and `list_reminders` calls
do not replace the saved receipts with model prose. Additional router commentary
is not appended to these confirmations; independently verified scheduling
mismatches are reported alongside the receipt.
It is retained as unverified audit context on the reminder's existing tool trace
for Completion Guard; it is not another tool execution or saved-state evidence.

An independently parsed multi-reminder request is checked against successful
receipts before confirmation. A reminder-only turn may take one bounded recovery
step to complete explicitly requested missing notifications; it cannot recreate
an already covered notification. Recovery does not repeat unrelated actions or
replace a receipt with a different saved time. If notifications remain missing,
the answer retains actual receipts, identifies the unconfirmed requests, and
returns `error_code: incomplete_reminder_request` with `ok: false`. The same
check applies at duplicate and turn limits. Its warning survives follow-up
extraction within the existing context budget.

When a reminder shares a request with `status_recap`, `phone_call`, or
`generate_music`, their actual receipts are preserved verbatim in execution
order. Failed attempts are included. Mixed actions such as create/cancel/create
still use the router's whole-task answer, retaining any other direct-speech
receipts without replaying obsolete reminder-create confirmations.
These replies bypass the extra response-style summary pass in auto and casual
modes. The selected answer appears in both `speech` and `raw_llm_response`,
including for `/api/query`.

After a blocked repeat of `create_reminder`, recovery instructions prohibit
changing the title or time to retry that same reminder. Other tools retain their
existing different-call recovery guidance and duplicate-loop limits. Receipt
selection also applies when a reminder-only turn ends at the duplicate or turn
limit. Successful reminder completion guidance reaches both text follow-ups and
OpenAI/xAI native continuations.

For bounded daily schedules, receipts distinguish newly created reminders from
reused active rows. The legacy `reminders_created` field still counts requested
occurrences for compatibility; `newly_created_count`, `reminders_reused`, and
`reminders_total` expose the actual breakdown.

Web follow-up context keeps the request title/description, saved UTC/local
times, recurrence, original schedule and selectors, reference clock/timezone,
Calendar status, and insert/reuse counts. A bounded batch retains up to all 366
reminder IDs, plus its first/last occurrence and a small detail sample. Repeated
receipts share a bounded context budget; omitted IDs or details are marked and
require `list_reminders` before acting on them. Schedule rejections retain their
clarification question and failed status, without inventing a saved reminder ID.

Completion Guard can audit these outcomes in automatic or manual mode. Its
repair pass verifies attempted reminder creations with a read-only tool scope;
it does not create replacements or cancel reminders. See
[Built-in reminder review](../COMPLETION_GUARD.md#built-in-reminder-review),
including the explicit-exclusion setting required on older installations.

Direct `POST /api/reminders` and Memory UI creation bypass
the tool parser and conversational confirmation; their contracts are unchanged.
Deterministic workflow steps bypass conversational confirmation, but steps
executing `create_reminder` use its schedule validation just like other callers.

### Supported Time Expressions

**Relative:**
- "in X minutes" → `in 30 minutes`
- "in X hours" → `in 4 hours`
- "in X days" → `in 2 days`
- "in X weeks" → `in two weeks`
- Compound: "in 1 hour 30 minutes"
- Fractional: "in half an hour", "in an hour and a half", "in 1.5 hours"

**Absolute:**
- "tomorrow at 3pm"
- "Monday at 5pm", "on Monday at 17:00", "5pm on Monday"
- "a week from Monday at 5pm"
- "today at noon", "day after tomorrow at 3pm"
- "November 9 at 5pm", "9 November 2026 at 17:00"
- "2026-11-09T17:00:00-08:00" (explicit date and UTC offset)
- "at 5pm" (today if not passed, else tomorrow)
- Structured selectors support additional conversational phrasing; unsupported
  expressions are clarified rather than partially parsed.

Bounded daily examples include `for a week at 9am` (seven notifications,
including today if that time is still ahead) and `every day this week at 5pm`
(remaining dates through Sunday). Vague times such as `soon`, ambiguous numeric
dates such as `11/9`, and recurrence the scheduler cannot represent (for example,
`every other day` or `every two hours`) require clarification.
Comparative requests such as `before Monday at 5pm` or `in less than an hour`
also require an exact notification time; their boundary is never silently used
as the reminder time.

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

### Cancel Reminder

Cancels a scheduled reminder (sets `status=canceled`; row is retained):

```bash
DELETE /api/reminders/{id}
```

### Permanently Delete Reminder

Hard-deletes the reminder row:

```bash
DELETE /api/reminders/{id}?permanent=true
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

The voice tool returns each reminder with both UTC and local time:

| Field | Example | Notes |
|-------|---------|-------|
| `trigger_time` | `2026-02-12T01:00:00.000002` | UTC (database value) |
| `trigger_time_local` | `Wednesday, February 11, 2026 at 05:00 PM PST` | Converted using `JARVIS_TIMEZONE` |
| `relative_time` | `in 21 hours` | Human-friendly relative |

This helps the LLM reason about times without needing UTC-to-local conversion.
The REST API (`/api/reminders`) returns UTC only, which is correct for external consumers.

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
0 * * * * ~/jarvis-voice/sync-calendar.py
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
    status TEXT DEFAULT 'scheduled',  -- scheduled|triggered|acknowledged|canceled|expired
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

1. Check reminder_scheduler is running (most common cause!):
```bash
ps aux | grep reminder_scheduler
# If not running, the watchdog cron should auto-restart self_healing_daemon
# which in turn restarts reminder_scheduler. Check:
cat logs/watchdog.log
```

2. Check reminder exists and is scheduled:
```bash
curl http://localhost:8880/api/reminders?status=scheduled | jq
```

3. Check trigger time is in the past (UTC):
```bash
sqlite3 data/jarvis_memory.db "SELECT id, title, trigger_time, datetime('now') FROM reminders WHERE id=X;"
```

4. Check the scheduler log:
```bash
tail -f logs/reminder_scheduler.log
```

5. Restart services if needed:
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
