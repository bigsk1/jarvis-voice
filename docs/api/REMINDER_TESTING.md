# Reminder Testing Commands

## Create Reminders

### Via Voice
```bash
./jarvis
# Say: "Remind me in 2 minutes to test this"
# Say: "Remind me every Wednesday to take out trash"
# Say: "Remind me every month on the 10th about Netflix"
```

### Via Tool (Direct)
```bash
# One-time reminder
echo '{"title": "Test reminder", "when": "in 2 minutes"}' | python3 skills/create_reminder.py

# Weekly recurring
echo '{"title": "Take out trash", "when": "every wednesday"}' | python3 skills/create_reminder.py

# Monthly recurring
echo '{"title": "Netflix bill", "when": "every month on the 10th at 9am"}' | python3 skills/create_reminder.py
```

### Via API
```bash
# One-time (UTC time required!)
curl -X POST http://localhost:8880/api/reminders \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Team Meeting",
    "trigger_time": "2025-11-24T15:00:00"
  }'

# Recurring (add recurrence_rule)
curl -X POST http://localhost:8880/api/reminders \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Weekly Standup",
    "trigger_time": "2025-11-22T15:00:00",
    "recurrence_rule": "WEEKLY:4"
  }'
```

## List Reminders

### Via Voice
```bash
./jarvis
# Say: "What reminders do I have?"
# Say: "Did I miss any reminders?"
# Say: "Show me scheduled reminders"
```

### Via Tool (Direct)
```bash
# All reminders
echo '{"status": "all"}' | python3 skills/list_reminders.py | jq -r '.speech'

# Only scheduled (upcoming)
echo '{"status": "scheduled"}' | python3 skills/list_reminders.py | jq

# Only triggered (missed, not acknowledged)
echo '{"status": "triggered"}' | python3 skills/list_reminders.py | jq

# Get IDs for specific actions
echo '{"status": "scheduled"}' | python3 skills/list_reminders.py | jq '.data.reminders[] | {id, title}'
```

### Via API
```bash
# All reminders
curl http://localhost:8880/api/reminders | jq

# Filter by status
curl http://localhost:8880/api/reminders?status=scheduled | jq
curl http://localhost:8880/api/reminders?status=triggered | jq
```

## Acknowledge (Clear) Reminders

### Via Voice
```bash
./jarvis
# Say: "Clear all my reminders"
# Say: "Clear reminder 11"
# Say: "Acknowledge reminders 11 and 12"
# Say: "Mark my trash reminder as done"
```

### Via Tool (Direct)
```bash
# Clear all pending reminders (scheduled + triggered)
echo '{"all_triggered": true}' | python3 skills/acknowledge_reminders.py

# Clear specific reminders by ID
echo '{"reminder_ids": [11, 12]}' | python3 skills/acknowledge_reminders.py

# Clear just one
echo '{"reminder_ids": [13]}' | python3 skills/acknowledge_reminders.py
```

### Via API
```bash
# Acknowledge all pending
curl -X POST http://localhost:8880/api/reminders/acknowledge-all

# Acknowledge specific reminder
curl -X POST http://localhost:8880/api/reminders/11/acknowledge

# Delete reminder entirely
curl -X DELETE http://localhost:8880/api/reminders/11
```

## Database Queries (Testing)

```bash
# View all reminders with details
sqlite3 data/jarvis_memory.db "SELECT id, title, status, trigger_time, recurrence_rule FROM reminders ORDER BY trigger_time;"

# Check specific reminder
sqlite3 data/jarvis_memory.db "SELECT * FROM reminders WHERE id = 11;"

# Find reminders by title
sqlite3 data/jarvis_memory.db "SELECT id, title, status FROM reminders WHERE title LIKE '%trash%';"

# Count by status
sqlite3 data/jarvis_memory.db "SELECT status, COUNT(*) FROM reminders GROUP BY status;"

# Delete test reminders
sqlite3 data/jarvis_memory.db "DELETE FROM reminders WHERE title LIKE 'Test%';"

# Clear ALL reminders (careful!)
sqlite3 data/jarvis_memory.db "DELETE FROM reminders;"
```

## Quick Test Workflow

```bash
# 1. Create a test reminder (2 minutes)
echo '{"title": "Test Reminder", "when": "in 2 minutes"}' | python3 skills/create_reminder.py

# 2. List to see it
echo '{"status": "scheduled"}' | python3 skills/list_reminders.py | jq -r '.speech'

# 3. Wait 2 minutes, check triggered
echo '{"status": "triggered"}' | python3 skills/list_reminders.py | jq -r '.speech'

# 4. Clear it
echo '{"all_triggered": true}' | python3 skills/acknowledge_reminders.py

# 5. Verify it's gone
echo '{"status": "all"}' | python3 skills/list_reminders.py | jq -r '.speech'
```

## Recurring Reminder Test

```bash
# Create recurring reminder (30 seconds for testing)
sqlite3 data/jarvis_memory.db "INSERT INTO reminders (title, trigger_time, status, recurrence_rule) VALUES ('Test Weekly', datetime('now', '+30 seconds'), 'scheduled', 'WEEKLY:2');"

# Watch scheduler logs
tail -f logs/services/reminder_scheduler-$(date +%Y-%m-%d).log

# After it triggers, check it was rescheduled
sqlite3 data/jarvis_memory.db "SELECT id, title, status, trigger_time, recurrence_rule FROM reminders WHERE title = 'Test Weekly';"
# Should show status='scheduled' with new trigger_time (+7 days)
```
