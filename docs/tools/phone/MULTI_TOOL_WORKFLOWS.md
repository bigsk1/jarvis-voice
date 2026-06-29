# Multi-Tool Workflows with Phone Calls

The real power of Jarvis is chaining multiple tools together to accomplish complex real-world tasks.

## The Vision

```
"Hey Jarvis, call john as Samantha and ask about the flight tomorrow,
then create a reminder with the flight info"
```

Jarvis should:
1. **Call** john using female persona (Samantha)
2. **Extract** flight details from the conversation
3. **Save** info to Canvas and Memory
4. **Create** a reminder synced to Google Calendar
5. **Speak** the reminder at the right time

---

## Example Workflows

### 🛫 Flight Info → Calendar Reminder

```
You: "Call john and get his flight details, then remind me when to pick him up"

Jarvis Flow:
1. phone_call → Call john, ask about flight
2. [Transcript saved to Canvas + Memory]
3. create_reminder → "Pick up john - Flight UA123 arrives 3:45pm at PDX"
4. n8n webhook → Syncs to Google Calendar
5. [30 mins before] Jarvis speaks: "Reminder: Pick up john in 30 minutes"
```

### 🎬 Movie Plans → Group Coordination

```
You: "Call Andrew and Boss, ask if they want to see Gladiator II tonight,
      then book the 9pm showing if they agree"

Jarvis Flow:
1. phone_call → Call Andrew, ask about movie
2. phone_call → Call Boss, ask about movie
3. [Results saved to Memory]
4. If both agree:
   - send_email → Send confirmation to both
   - create_reminder → "Gladiator II at Regal, 9pm"
   - canvas → Save movie night details
```

### 🍽️ Dinner Decision → Order Placement

```
You: "Call the family and figure out what everyone wants for dinner"

Jarvis Flow:
1. phone_call → Call Mom, ask dinner preference
2. phone_call → Call Dad, ask dinner preference
3. [Preferences saved to Memory]
4. Jarvis: "Mom wants Italian, Dad wants tacos. Should I look up restaurants?"
5. mcp_brave_search → Find nearby options
6. send_email → Share restaurant options with family
```

### 📋 Appointment Confirmation → Logistics

```
You: "Call the dentist and confirm my appointment, then remind me the day before"

Jarvis Flow:
1. phone_call → Call dentist office, confirm appointment
2. [Details extracted: Date, time, address]
3. create_reminder → Day before + morning of
4. canvas → Save appointment details
5. If rescheduled: update_memory → Store new time
```

---

## How It Works

### Automatic Data Flow

When a phone call completes, Jarvis automatically:

| Action | Tool | Purpose |
|--------|------|---------|
| Save transcript | `canvas` | Full record in "Phone Calls/" folder |
| Save summary | `memory` | Quick recall ("What did john say about...?") |
| Extract key info | LLM | Dates, times, confirmations, action items |

### Chaining Tools

The orchestrator can call multiple tools in sequence:

```python
# Turn 1: Make the call
phone_call(recipient="john", task="Get flight details", persona="female")

# Turn 2: Create reminder from results
create_reminder(message="Pick up john - Flight arrives 3:45pm PDX", time="3:15pm tomorrow")

# Turn 3: Confirm to user
"Done! I called john - his flight UA123 arrives at 3:45pm tomorrow.
 I've set a reminder for 3:15pm to pick him up."
```

### Memory Enables Context

Because call summaries are saved to memory, Jarvis can answer follow-ups:

```
You: "What time was john's flight again?"
Jarvis: [searches memory] "john's flight UA123 arrives at 3:45pm at PDX"

You: "Actually, remind me 1 hour before instead"
Jarvis: [updates reminder] "Updated! I'll remind you at 2:45pm"
```

---

## Current Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| Phone calls | ✅ | Via Vapi.ai |
| Canvas save | ✅ | Auto-saves transcripts |
| Memory save | ✅ | Auto-saves summaries |
| Reminders | ✅ | Via n8n → Google Calendar |
| Email | ✅ | Via n8n webhook |
| Multi-turn | ✅ | Orchestrator handles tool chains |
| Voice output | ✅ | Speaks results and reminders |

---

## Future Ideas

### Smart Follow-ups
After a call completes, Jarvis could suggest next actions:
```
Jarvis: "Call complete. john's flight is at 3:45pm.
        Would you like me to set a reminder to pick him up?"
```

### Persona Memory
Remember which persona works best for each contact:
```
- john prefers casual Jay
- Mom likes professional James
- Boss is fine with default Jarvis
```

### Call Scheduling
```
You: "Call john tomorrow morning to confirm the pickup"
Jarvis: [creates scheduled call for 9am tomorrow]
```

### Conference Calls
```
You: "Get Andrew and Boss on a call to plan the weekend"
Jarvis: [initiates 3-way call or sequential calls with summary]
```

### Voicemail Follow-up
```
[john doesn't answer, voicemail detected]
Jarvis: "john didn't answer. Want me to send a text instead,
        or try again in 30 minutes?"
```

### Call Chains → Call Back with Results
```
You: "Call Andrew about the movie, then call Boss to see if he's in,
      then call me back with the results"

Jarvis Flow:
1. phone_call → Andrew: "Want to see Gladiator II tonight?"
   → Andrew: "Yeah, 9pm works"
2. phone_call → Boss: "Andrew's in for 9pm, you?"
   → Boss: "I'm in, let's do it"
3. phone_call → YOU: "Hey Boss, both Andrew and Boss confirmed
   for Gladiator II at 9pm. Should I set a reminder?"
```

**Technical Note:** Sequential calls require the lock to clear between calls.
Current behavior:
- 120s cooldown per number (prevents spam to same person)
- Global "in-progress" lock (prevents parallel calls)
- Lock clears when call ends

For call chains to work smoothly:
- Each call must complete before next starts (WAIT=true mode)
- Different numbers = no cooldown conflict
- Same number = 120s wait (configurable)

---

## Tips for Complex Tasks

1. **Be specific about the task**: "Ask about his flight tomorrow" vs just "call john"
2. **Chain with "then"**: "Call john, then create a reminder"
3. **Mention the persona**: "Call as Samantha" or "use professional James"
4. **Ask for confirmation**: "...and let me know what he says"

---

## Related Docs

- [Phone Calls Setup](PHONE_CALLS.md) - Basic phone tool configuration
- [Reminders](../../api/REMINDER_SYSTEM.md) - Reminder system with Google Calendar sync
- [Memory System](../../MEMORY_SYSTEM.md) - How Jarvis remembers things
- [Canvas](../../CANVAS_SYSTEM.md) - Persistent note storage

---

*This is the vision: Jarvis as a true AI assistant that can handle complex,
multi-step real-world tasks through natural conversation.*
