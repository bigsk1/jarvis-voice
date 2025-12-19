# AI Phone Calls with Jarvis (via Vapi.ai)

Jarvis can make outbound AI phone calls on your behalf, have conversations, and report back with results.

## Quick Start

```
"Hey Jarvis, call Boss and ask if he wants to see Gladiator II at 9pm tonight"
```

Jarvis will:
1. Call Boss's phone
2. Introduce himself as your AI assistant
3. Explain the movie invitation
4. Have a conversation to get a response
5. Report back: "Boss said yes, he'll meet you at Regal at 9pm"

---

## Two Modes

| Mode | `VAPI_WAIT_FOR_CALL` | Behavior |
|------|---------------------|----------|
| **Sync** | `true` (default) | Wait up to 60s for call, get instant results |
| **Async** | `false` | Return immediately, ask "what happened on that call?" later |

Both modes auto-save transcripts to Canvas in the `Phone Calls/` folder.

**Sync Mode** (recommended): 
- Best for short calls where you want immediate feedback
- "Call boss and ask about dinner" → *waits* → "They said tacos!"

**Async Mode**:
- Best for longer calls or when you don't need to wait
- "Call boss" → "Calling now" → *later* → "What happened?" → "They agreed!"

## Voicemail Handling

| `VAPI_VOICEMAIL_ACTION` | Behavior |
|------------------------|----------|
| `hangup` (default) | Detect voicemail and hang up - no message left |
| `message` | Detect voicemail and leave a short callback message |
| `disabled` | Don't detect - AI talks to voicemail like it's a person (weird) |

---

## Setup (One-Time)

### 1. Create Vapi.ai Account

1. Go to [vapi.ai](https://vapi.ai) and sign up
2. Navigate to **Organization Settings > API Keys**
3. Copy your **Private Key** (this is your API key)

### 2. Get a Phone Number

1. In Vapi dashboard, go to **Phone Numbers**
2. Purchase a number or import an existing one
3. Copy the **Phone Number ID**

### 3. Configure Jarvis

Add to `config/cloud.env`:

```bash
# Vapi.ai Phone Calls
VAPI_API_KEY="your_private_key_here"
VAPI_PHONE_NUMBER_ID="your_phone_number_id"
OWNER_NAME="Boss"  # How Jarvis identifies you
VAPI_WAIT_FOR_CALL=true  # true=wait for result, false=async
```

### 4. Sync Tools

```bash
./bin/sync_tools.py cloud
```

---

## What You Can Say

### Make a Call

| What You Say | What Happens |
|--------------|--------------|
| "Call Boss and ask about the movie" | Calls Boss with the task |
| "Call +15551234567 and confirm the appointment" | Calls number directly |
| "Call Andrew as professional James" | Uses formal persona |
| "Call Mom and wish her happy birthday" | Personal call with context |

### Check Call Status

| What You Say | What Happens |
|--------------|--------------|
| "What happened with that call?" | Gets call result/transcript |
| "List my recent phone calls" | Shows recent calls |

### Manage Contacts

| What You Say | What Happens |
|--------------|--------------|
| "Save Andrew's number as +15551234567" | Adds to contacts |
| "Who's in my phone contacts?" | Lists saved contacts |

---

## Personas

Jarvis can adopt different communication styles:

### Default (Jarvis)
> "Hi, this is Jarvis calling on behalf of Boss..."
- Friendly and professional
- Gets to the point
- Natural conversational style

### Professional (James)
> "Good day, this is James calling on behalf of Boss..."
- Formal British butler style
- Very polite and articulate
- Uses formal language

### Casual (Jay)
> "Hey! This is Jay calling for Boss..."
- Relaxed and friendly
- Like talking to a buddy
- Conversational and light

### Female (Samantha)
> "Hi there! This is Samantha calling on behalf of Boss..."
- Female voice (OpenAI nova or ElevenLabs if configured)
- Warm and engaging
- Friendly and personable

**Usage:**
```
"Call Boss using the professional persona"
"Call Andrew as casual Jay"
"Call Mom using the female persona"  # Aria
```

---

## Examples

### Movie Invitation
```
You: "Hey Jarvis, call Andrew and ask if he wants to catch 
      Gladiator II at Regal tonight. The 9pm showing looks good."

Jarvis: [Calls Andrew]
  "Hi Andrew, this is Jarvis calling on behalf of Boss. 
   He wanted to know if you'd like to catch Gladiator II 
   at Regal tonight - there's a 9pm showing. What do you think?"

Andrew: "Yeah that sounds great, tell him I'm in!"

Jarvis: [Reports back]
  "Andrew said yes! He's in for the 9pm showing at Regal."
```

### Appointment Confirmation
```
You: "Call the dentist office at +15035551234 and confirm 
      my appointment for tomorrow at 2pm"

Jarvis: [Calls office]
  "Hi, this is Jarvis calling on behalf of Boss. I'm calling 
   to confirm his dental appointment scheduled for tomorrow 
   at 2pm. Is that still on the schedule?"

Office: "Yes, we have him down for 2pm tomorrow. We'll see him then!"

Jarvis: "Your dentist appointment is confirmed for tomorrow at 2pm."
```

### Quick Check-In
```
You: "Call Mom and see if she needs anything from the store"

Jarvis: [Calls Mom]
  "Hi! This is Jarvis, Boss's AI assistant. He's heading to 
   the store and wanted to check if you need anything."

Mom: "Oh how sweet! Tell him to grab some milk please."

Jarvis: "Mom says she'd like you to pick up some milk."
```

---

## Technical Details

### Actions Available

| Action | Description | Parameters |
|--------|-------------|------------|
| `call` | Make an outbound call | `recipient`, `task`, `context`, `persona` |
| `status` | Check call status | `call_id` |
| `list` | List recent calls | `limit` |
| `contacts` | Manage contacts | `add_name`, `add_number` |

### Config Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `VAPI_API_KEY` | Vapi private API key | ✅ Yes |
| `VAPI_PHONE_NUMBER_ID` | Your Vapi phone number ID | ✅ Yes |
| `VAPI_WAIT_FOR_CALL` | `true` to wait for result, `false` for async | No (default: true) |
| `VAPI_VOICEMAIL_ACTION` | `hangup`, `message`, or `disabled` | No (default: hangup) |
| `VAPI_ASSISTANT_ID` | Pre-configured assistant (bypasses personas) | No |
| `VAPI_VOICE_ID` | ElevenLabs voice ID for male personas | No |
| `VAPI_FEMALE_VOICE_ID` | ElevenLabs voice ID for female persona | No |
| `VAPI_LLM_PROVIDER` | LLM for calls: xai, anthropic, openai | No (default: xai) |
| `VAPI_LLM_MODEL` | Specific model to use | No |
| `OWNER_NAME` | How Jarvis identifies you | No (default: "Boss") |
| `PHONE_CONTACTS` | JSON map of name→number | No |

### Memory Integration

Call summaries are automatically saved to Jarvis's memory, allowing:
- "What did Andrew say about dinner?"
- "When did I call Mom last?"
- "What was the outcome of that phone call?"

Full transcripts are also saved to Canvas in the `Phone Calls/` folder.

### Files

| File | Purpose |
|------|---------|
| `skills/phone_call.py` | Main tool implementation |
| `skills/phone_call.tool.json` | Tool definition for LLM |
| `docs/phone/PHONE_CALLS.md` | This documentation |

### API Costs

Vapi.ai pricing (approximate):
- ~$0.05/minute for calls
- Additional costs for LLM and TTS usage
- Check [vapi.ai/pricing](https://vapi.ai/pricing) for current rates

---

## Saving Contacts

### Via Voice
```
"Hey Jarvis, save Andrew's phone number as +15551234567"
```

### Via Memory
```
"Hey Jarvis, remember that Andrew's phone is +15551234567"
```

### Via Config
Add to `config/cloud.env`:
```bash
PHONE_CONTACTS='{"andrew": "+15551234567", "mom": "+15559876543"}'
```

---

## Troubleshooting

### "VAPI_API_KEY not configured"
Add your Vapi private key to `config/cloud.env`

### "VAPI_PHONE_NUMBER_ID not configured"
1. Go to Vapi dashboard > Phone Numbers
2. Purchase or import a number
3. Copy the ID and add to config

### "Could not find phone number for X"
Either:
- Use full number with country code: "+15551234567"
- Add to contacts first: "Save X's number as +1555..."

### Call doesn't connect
- Verify the phone number is correct with country code
- Check Vapi dashboard for call logs and errors
- Ensure your Vapi account has credit

### AI talks to voicemail greeting (Dec 2025 fix)
**Symptom:** AI starts conversation with the voicemail greeting message instead of detecting it.

**Root cause:** Default voicemail detection wasn't aggressive enough.

**Fix applied in `phone_call.py`:**
```python
voicemail_detection_config = {
    "provider": "vapi",
    "backoffPlan": {
        "startAtSeconds": 1.5,    # Start checking early (was 2)
        "frequencySeconds": 2.5,  # Minimum interval
        "maxRetries": 8           # More attempts (was 5)
    },
    "beepMaxAwaitSeconds": 12
}
```

See: [VAPI voicemail detection docs](https://docs.vapi.ai/api-reference/assistants/create#request.body.voicemailDetection)

### Transcript truncated or missing (Dec 2025 fix)
**Symptom:** Canvas transcript page is truncated or LLM creates a separate canvas page with incomplete transcript.

**Root causes:**
1. **VAPI returns transcript in different formats** - Pre-configured assistants (via `VAPI_ASSISTANT_ID`) return `messages` array instead of `transcript` string
2. **LLM creates duplicate canvas** - Doesn't know phone_call tool already auto-saves to Canvas

**Fixes applied:**

1. **`extract_transcript()` function** - Checks 3 sources for best transcript:
   - `call['transcript']` - plain text (dynamic assistants)
   - `call['messages']` - array format (pre-configured assistants)
   - `call['artifact']['transcript']` - from artifact plan

2. **Clear messaging** - Tool now says "Full transcript already saved to Canvas in Phone Calls folder" so LLM doesn't create duplicates

**If transcript seems missing:**
- Check Canvas `Phone Calls/` folder - it's likely there
- Browser refresh may be needed
- Async mode (`VAPI_WAIT_FOR_CALL=false`) creates canvas after call ends, not immediately

### Canvas shows two transcript pages
**Symptom:** One complete transcript in `Phone Calls/2025-...` and one truncated in custom-named page.

**Cause:** LLM called `canvas` tool with truncated data instead of using phone_call's auto-saved page.

**Fix:** Phone_call tool now explicitly tells LLM the transcript is already saved. The correct page is always in `Phone Calls/` folder with timestamp naming.

---

## Future Ideas

- [ ] Incoming call handling (Jarvis answers calls)
- [ ] Call scheduling ("Call Boss tomorrow at 9am")
- [ ] Call recording transcription storage
- [ ] Group calls / conference bridges
- [ ] SMS/text message support
- [ ] Custom voice cloning for calls

---

## Privacy & Security

- Phone numbers are stored in memory DB or config
- Call transcripts can be stored for reference
- Vapi handles call encryption and security
- Consider GDPR/privacy implications for recording

---

**Last Updated:** 2025-12-18

