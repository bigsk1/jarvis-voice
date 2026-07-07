# Jarvis ↔ Google Calendar Bidirectional Sync

## Overview

This document describes the bidirectional synchronization between Jarvis reminders and Google Calendar events using n8n workflows.

```
┌───────────────────┐                      ┌─────────────────┐
│  Jarvis (70.228)  │    n8n Webhook       │     Google      │
│    Reminders      │ ──────────────────►  │    Calendar     │
│   API :8880       │                      │                 │
│                   │    n8n Trigger       │                 │
│                   │ ◄──────────────────  │                 │
└───────────────────┘                      └─────────────────┘
          │                                        │
          │           ┌─────────────────┐          │
          └──────────►│  n8n (70.226)   │◄─────────┘
                      │     :5678       │
                      └─────────────────┘
```

## Network Architecture

| Service | IP Address | Port | Description |
|---------|------------|------|-------------|
| Jarvis API | localhost | 8880 | Reminder API endpoints |
| n8n | localhost | 5678 | Workflow automation |
| Google Calendar | cloud | - | External API |

## Sync Directions

### Direction 1: Jarvis → Google Calendar

When a reminder is created in Jarvis:
1. Jarvis `create_reminder` tool creates reminder in SQLite
2. Calls n8n webhook to sync to Google Calendar
3. n8n workflow creates Google Calendar event with `[Jarvis]` prefix
4. Google Calendar event ID stored in Jarvis reminder metadata

### Direction 2: Google Calendar → Jarvis

When an event is created/modified/deleted in Google Calendar:
1. Google Calendar Trigger (n8n) polls for changes (~1 min interval)
2. n8n workflow filters out `[Jarvis]` prefixed events (to avoid loops)
3. n8n calls appropriate Jarvis API endpoint:
   - **eventCreated** → `POST /api/reminders` (create)
   - **eventUpdated** → `PUT /api/reminders/by-gcal/{id}` (update)
   - **eventCancelled** → `DELETE /api/reminders/by-gcal/{id}` (cancel)
4. Reminder stored with `source: google_calendar` metadata

## n8n Workflows

### Workflow 1: Jarvis → Google Calendar

**Webhook URL**: `http://localhost:5678/webhook/jarvis-reminder`

**Input Payload**:
```json
{
  "action": "create",
  "reminder": {
    "id": 123,
    "title": "Dentist appointment",
    "description": "Annual checkup",
    "trigger_time": "2025-11-26T11:00:00Z",
    "recurrence_rule": "WEEKLY:2"
  }
}
```

**Response**:
```json
{
  "ok": true,
  "gcal_event_id": "abc123xyz",
  "message": "Event created in Google Calendar"
}
```

### Workflow 2: Google Calendar → Jarvis

**Triggers**: 
- `GCal Event Created` - New events
- `GCal Event Updated` - Modified events  
- `GCal Event Cancelled` - Deleted events

**Nodes** (9 total):
- GCal Event Created → Skip Jarvis Events → Create Jarvis Reminder → Log Result
- GCal Event Updated → Skip Jarvis Events (Update) → Update Jarvis Reminder → Log Result
- GCal Event Cancelled → Cancel Jarvis Reminder → Log Result

**Create Jarvis API Call**:
```bash
POST http://localhost:8880/api/reminders
Content-Type: application/json

{
  "title": "Meeting with John",
  "description": "Discuss Q4 planning",
  "trigger_time": "2025-11-26T15:00:00Z",
  "metadata": {
    "source": "google_calendar",
    "gcal_event_id": "abc123xyz",
    "gcal_calendar_id": "primary"
  }
}
```

**Update Jarvis API Call**:
```bash
PUT http://localhost:8880/api/reminders/by-gcal/{gcal_event_id}
Content-Type: application/json

{
  "title": "Meeting with John (updated)",
  "description": "Rescheduled",
  "trigger_time": "2025-11-26T16:00:00Z",
  "metadata": {
    "source": "google_calendar",
    "gcal_event_id": "abc123xyz",
    "updated_from_gcal": true
  }
}
```

Updating a reminder through this synchronization path reactivates it as
`scheduled` and clears its previous trigger, acknowledgement, and spoken
timestamps. A calendar event moved after it already fired or was canceled will
therefore fire once at its newly synchronized time.

**Delete Jarvis API Call**:
```bash
DELETE http://localhost:8880/api/reminders/by-gcal/{gcal_event_id}
```

## Jarvis API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/reminders` | Create reminder |
| GET | `/api/reminders` | List reminders |
| GET | `/api/reminders/{id}` | Get specific reminder |
| PUT | `/api/reminders/{id}` | Update reminder |
| DELETE | `/api/reminders/{id}` | Cancel reminder |
| POST | `/api/reminders/{id}/acknowledge` | Acknowledge reminder |
| POST | `/api/reminders/acknowledge-all` | Acknowledge all triggered |
| GET | `/api/reminders/by-gcal/{gcal_id}` | Get by Google Calendar ID |
| PUT | `/api/reminders/by-gcal/{gcal_id}` | Update by Google Calendar ID |
| DELETE | `/api/reminders/by-gcal/{gcal_id}` | Cancel by Google Calendar ID |

## Metadata Schema

**Reminders synced FROM Google Calendar**:
```json
{
  "source": "google_calendar",
  "gcal_event_id": "event_abc123",
  "gcal_calendar_id": "primary",
  "synced_at": "2025-11-25T10:00:00Z"
}
```

**Reminders synced TO Google Calendar**:
```json
{
  "gcal_event_id": "event_xyz789",
  "gcal_synced": true,
  "gcal_synced_at": "2025-11-25T10:00:00Z"
}
```

## Avoiding Sync Loops

To prevent infinite sync loops:

1. **Jarvis → GCal**: Events created with `[Jarvis]` prefix in title
2. **GCal → Jarvis**: Filter node skips events starting with `[Jarvis]`
3. **Metadata tracking**: `source: google_calendar` identifies GCal-originated reminders

## Timezone Handling (Critical!)

**All times must be stored in UTC format** for correct comparison:

```
✅ Correct:   2025-11-25T15:00:00Z      (UTC with Z suffix)
❌ Wrong:     2025-11-25T07:00:00-08:00 (with timezone offset)
```

**Why?** SQLite compares times as strings. With timezone offsets, `07:00:00-08:00` 
(which equals 15:00 UTC) would incorrectly match before `12:00:00Z` because 
`07` < `12` alphabetically.

The n8n workflow converts Google Calendar times to UTC:
```javascript
DateTime.fromISO($json.start.dateTime).toUTC().toFormat("yyyy-MM-dd'T'HH:mm:ss'Z'")
```

## Configuration

### Environment Variables

Add to `config/cloud.env` and `config/local.env`:
```bash
# n8n Integration (Google Calendar Sync)
N8N_LOCAL_API_URL="http://localhost:5678"
N8N_LOCAL_API_KEY="your-n8n-api-key"
N8N_JARVIS_WEBHOOK_URL="http://localhost:5678/webhook/jarvis-reminder"
```

### n8n Credentials Required

1. **Google Calendar OAuth2**
   - Create OAuth 2.0 credentials in Google Cloud Console
   - Enable Google Calendar API
   - Configure in n8n credentials

2. **Jarvis API** (optional, for authenticated calls)
   - Header Auth if needed

### Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create or select a project
3. Enable **Google Calendar API**
4. Create OAuth 2.0 credentials (Desktop app type for localhost)
5. Add your email as a test user (for unpublished apps)
6. Configure credentials in n8n

## n8n Workflow IDs

| Workflow | ID | Status |
|----------|-----|--------|
| Jarvis → Google Calendar Sync | `rDqYkqg6otOWzgX2` | Active |
| Google Calendar → Jarvis Sync | `ckEvanjTTZJGiH0V` | Active |
| Calendar Agent (AI) | `Chq72hZHoFxWMG1A` | Available |

## Testing

### Test Jarvis → GCal
```bash
# Via voice or CLI
./jarvis-local "Remind me Wednesday at 11am to go to dentist"

# Or test webhook directly
curl -X POST http://localhost:5678/webhook/jarvis-reminder \
  -H "Content-Type: application/json" \
  -d '{"action":"create","reminder":{"id":1,"title":"Test","trigger_time":"2025-11-26T11:00:00Z"}}'
```

### Test GCal → Jarvis
```bash
# 1. Create event in Google Calendar (web/mobile)
# 2. Wait ~5 minutes for n8n trigger
# 3. Check Jarvis reminders
curl http://localhost:8880/api/reminders | jq
```

## Troubleshooting

### Webhook not working
1. Verify n8n workflow is active (green toggle)
2. Check webhook URL: `http://localhost:5678/webhook/jarvis-reminder`
3. Check n8n execution logs for errors

### Google Calendar API errors
1. Ensure Google Calendar API is enabled
2. Verify OAuth credentials are valid
3. Check if your email is added as test user (for unpublished apps)
4. Re-authenticate in n8n if token expired

### Duplicate reminders
1. Check if `[Jarvis]` prefix filter is working
2. Verify metadata `source` field
3. Check n8n filter node configuration

## Related Files

- `skills/create_reminder.py` - Jarvis reminder tool (calls webhook)
- `api/routes/reminders.py` - Reminder API endpoints
- `api/managers/reminder_manager.py` - Reminder business logic
- `docs/api/REMINDER_SYSTEM.md` - Full reminder documentation
