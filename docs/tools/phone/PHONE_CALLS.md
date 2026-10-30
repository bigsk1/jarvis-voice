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

## Foreground wait modes

| Mode | `VAPI_WAIT_FOR_CALL` | Behavior |
|------|---------------------|----------|
| **Sync** | `true` | Wait for the result, up to `VAPI_WAIT_TIMEOUT` (900 seconds by default) |
| **Async** | `false` (code default) | Return immediately, ask "what happened on that call?" later |

The example configuration selects sync mode. Completed calls with transcripts
are saved to Canvas in `Phone Calls/` when the tool observes completion. Async
mode needs a later status check or call request unless the optional Web background
path below is selected. A wait timeout leaves the active call tracked for later
inspection. Foreground subprocesses allow the configured wait plus 450 seconds
for submission, final polling, recording retrieval and saving.

**Sync Mode** (recommended): 
- Best for short calls where you want immediate feedback
- "Call boss and ask about dinner" → *waits* → "They said tacos!"

**Async Mode**:
- Best for longer calls or when you don't need to wait
- "Call boss" → "Calling now" → *later* → "What happened?" → "They agreed!"

### Optional Web background calls

Select **Phone call** in **Settings → Tools → Background tasks**, with the
master switch enabled and a ready task worker. This uses the existing
`remote_skill_v1` runner: the worker places one call, polls Vapi over outbound
HTTPS, collects its files, and delivers the result in the originating Web
conversation while chat remains free. No public endpoint or incoming callback
is required. Installing this capability does not change saved preferences.

Only `call` actions use background admission. Status, list and contact actions
remain foreground. API, CLI, native voice, Talk and workflow calls retain the
foreground behavior above. Background calls always observe completion even if
`VAPI_WAIT_FOR_CALL=false`. Their total budget is 1,200 seconds, including queue
time and saving; the observer reserves time for collecting results.

Progress reports short phases such as queued, ringing, in progress and collecting
results, plus the Vapi call ID. It does not stream the conversation. Completed
calls automatically attempt Canvas saving, and save transcript/audio artifacts
to Stash; neither optional recording failure nor Canvas failure changes the
phone conversation's outcome.

The phone tool retains `dangerous: true` and `auto_approve: false`. A named,
reviewed production policy admits it through the shared remote runner; other
dangerous tools remain denied. Admission still requires the authenticated Web
request, saved tool selection, current manifest/script and restricted worker
environment. Only a terminal provider result can complete the background job.

A timeout, lost submission response or stopped worker leaves an uncertain task
with its available Vapi call ID. There is no automatic redial or observer resume
after restart. Check that existing call's status. Stopping observation does not
hang up the remote call; phone calls have no hangup action. See
[background tasks](../../BACKGROUND-TASKS.md) for recovery and operator controls.

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

### Saved assistant or generated assistant

When `VAPI_ASSISTANT_ID` is set, Jarvis uses that saved Vapi assistant. Its model,
voice, transcriber, voicemail, and recording settings come from Vapi. Jarvis
supplies `owner`, `task`, `reason`, `context`, and `recipient` as template
variables. Use the corresponding `{{task}}` and other placeholders in the saved
assistant's prompt. Changing Jarvis's chat model or the generated-assistant
settings below does not change a saved assistant.

Leave `VAPI_ASSISTANT_ID` empty or comment it out to use generated assistants:

```bash
# VAPI_ASSISTANT_ID="..."
VAPI_DEFAULT_PERSONA="female"  # Samantha, unless a call requests another persona
VAPI_LLM_PROVIDER="openai"
VAPI_LLM_MODEL="gpt-6-luna"
VAPI_LLM_REASONING_EFFORT="none"
VAPI_VOICE_MODEL="eleven_v4_turbo"
```

This creates a saved Vapi assistant for the call and then calls using its ID;
it does not send an inline transient assistant. Only the assistant created by
that call is eligible for cleanup after a terminal call result. Unrelated
assistants are never selected for deletion by their names.

Explicit `VAPI_LLM_PROVIDER` and `VAPI_LLM_MODEL` values are passed to Vapi
unchanged. The model must be supported by Vapi, which can offer a different
selection from Jarvis chat. `VAPI_LLM_REASONING_EFFORT` is an optional OpenAI
setting, independent of Jarvis's chat thinking level. Known models use the same
thinking capabilities in `lib/model_catalog.py` as Jarvis chat, limited to the
values Vapi's API accepts. GPT-6 Luna accepts `none` and rejects `minimal`;
Vapi's API does not currently accept `max`. Unknown models retain Vapi's
API-level validation. Omit the effort setting for other providers.

Other examples supported by Vapi include `xai` / `grok-4.3` and `deep-seek` /
`deepseek-flash`. DeepSeek requires connecting your own key in Vapi. xAI is
supported and can use Vapi's integration or a key connected there. See the
current [OpenAI](https://docs.vapi.ai/providers/model/openai),
[xAI](https://docs.vapi.ai/providers/model/xai), and
[DeepSeek](https://docs.vapi.ai/providers/model/deepseek) provider guides before
selecting a model. Latency depends on the complete call pipeline; these examples
are not measured speed rankings.

The optional voice model applies only when the generated assistant selects an
ElevenLabs voice. `VAPI_ELEVENLABS_KEY=true` is a local indication that ElevenLabs
has been connected in Vapi; it does not upload a credential. Connect the key in
Vapi and set `VAPI_VOICE_ID` or `VAPI_FEMALE_VOICE_ID` for that voice path.
`VAPI_DEFAULT_PERSONA` selects the generated persona when the call omits one;
an explicit persona still takes precedence. Set it to `female` for Samantha.

### 4. Sync Tools

```bash
source "${JARVIS_VENV:-$HOME/jarvis-venv}/bin/activate"
./bin/sync-tools.py cloud
```

---

## What You Can Say

### Make a Call

With generated assistants, requests can choose a persona per call:

| What You Say | What Happens |
|--------------|--------------|
| "Call Boss and ask about the movie" | Calls Boss with the task |
| "Call +15551234567 and confirm the appointment" | Calls number directly |
| "Call (212) 555-0199 as Samantha and ask their hours today" | Calls an unsaved number with the female persona |
| "Call 212-555-0199 as Jay and ask when they close" | Calls an unsaved number with the casual persona |
| "Call Andrew as professional James" | Uses formal persona |
| "Call Mom and wish her happy birthday" | Personal call with context |

An unsaved number goes directly in `recipient`; neither a contact nor a person's
name is required, and calling a number does not save it as a contact. Ten-digit
US numbers use `+1`; include `+` and the country code for international numbers.
For example, the first business request maps to:

```json
{
  "action": "call",
  "recipient": "(212) 555-0199",
  "persona": "female",
  "task": "Ask what hours the business is open today."
}
```

Omit `persona` to use `VAPI_DEFAULT_PERSONA`. Jay maps to `casual`, Samantha to
`female`, James to `professional`, and Jarvis to `default`. Bud is a saved Vapi
assistant, so it is selected through `VAPI_ASSISTANT_ID`, rather than a generated
persona.

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
"Call Mom using the female persona"  # Samantha
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
| `VAPI_WAIT_FOR_CALL` | `true` to wait for result, `false` for async | No (code default: false; example: true) |
| `VAPI_VOICEMAIL_ACTION` | `hangup`, `message`, or `disabled` | No (default: hangup) |
| `VAPI_ASSISTANT_ID` | Saved assistant; its Vapi settings override generated-assistant settings | No |
| `VAPI_DEFAULT_PERSONA` | Generated persona when omitted: `default`, `professional`, `casual`, or `female` (Samantha) | No (default: default) |
| `VAPI_VOICE_ID` | ElevenLabs voice ID for male personas | No |
| `VAPI_FEMALE_VOICE_ID` | ElevenLabs voice ID for female persona | No |
| `VAPI_VOICE_MODEL` | Optional ElevenLabs model for generated assistants | No |
| `VAPI_LLM_PROVIDER` | Generated-assistant LLM provider, using Vapi's provider names | No (default: openai) |
| `VAPI_LLM_MODEL` | Generated-assistant model, independent of Jarvis chat | No |
| `VAPI_LLM_REASONING_EFFORT` | Optional OpenAI reasoning effort for generated assistants | No |
| `VAPI_WAIT_TIMEOUT` | Maximum seconds to wait for call completion | No (default: 900) |
| `OWNER_NAME` | How Jarvis identifies you | No (default: "Boss") |
| `PHONE_CONTACTS` | JSON map of name→number | No |

### Memory Integration

Call summaries are automatically saved to Jarvis's memory, allowing:
- "What did Andrew say about dinner?"
- "When did I call Mom last?"
- "What was the outcome of that phone call?"

Full transcripts are also saved to Canvas in the `Phone Calls/` folder.

### Call artifacts and recording storage

Call status is retrieved with authenticated `GET /call/{id}`. The tool accepts
legacy fields and current `artifact.transcript`, `artifact.messages`, and
`analysis.summary` fields. Canvas save status reflects the Canvas tool's actual
result; successful call completion does not guarantee the transcript was saved.

Vapi recordings and log files now require authenticated download endpoints.
When a recording exists, the tool returns a stable
`https://api.vapi.ai/call/{id}/mono-recording` endpoint and indicates that
authentication is required. A backend must request it with the private Vapi
Bearer token and follow the redirect to a fresh, short-lived download URL.
The returned URL is not a public playback link. Do not place the private key in
a browser, URL, Canvas page, or tool output, or save the expiring redirect URL
for later playback. See [Vapi artifact retrieval](https://docs.vapi.ai/assistants/retrieve-call-artifacts).

When the tool observes a terminal call, it saves the written transcript and
summary as `transcript.md` in a per-call Stash space and attempts to retrieve
the combined recording. The private key is used only on Vapi's API request;
the signed redirect is downloaded separately and is never stored in metadata.
Audio downloads have size/time limits and must pass format checks. Stash uses
the configured `STASH_DIR` and source-artifact retention settings.

Saved audio returns `stash_ref`, `audio_stash_ref`, `filename`, `mime_type`,
`audio_saved: true`, and `audio_status: saved`. Web's existing audio player uses
that reference. Canvas includes recording and written-transcript links; its
existing audio player recognizes the recording. Status checks reuse saved audio
and stable transcript references rather than downloading another copy. A late
recording is appended to the same Canvas page without replacing user edits.
When Vapi supplies a later summary or fuller transcript, Jarvis appends a
labeled **Updated call results** section to that same page. A fingerprint of
the saved summary/transcript avoids repeating unchanged snapshots. Existing
pages without a fingerprint receive the current snapshot once on the next
status check. Failed Canvas writes leave the previous fingerprint unchanged
so a later check can retry. Stash's written transcript keeps its stable link
as its contents are refreshed.

If audio is missing, delayed or cannot be retrieved, the result retains the
call's outcome and transcript with `audio_saved: false`, `audio_status`
(`unavailable`, `pending`, or `failed`), and a sanitized `audio_error` when
available. A later status check can retry collection without redialing. Recording
enablement and storage settings remain in Vapi; Jarvis does not create a bucket.
An absent recording URL is reported as unavailable right now, rather than a
failed download or a promise that a recording will eventually appear.

A successful status lookup returns `ok: true` even if the call reached
voicemail, was busy, or was not answered; `call_failed` and `end_reason`
describe that outcome. Retrieval errors still return `ok: false`. Initial
unsuccessful calls continue to return `ok: false` with confirmed terminal
completion. Any terminal call with a transcript can save to Canvas, including
voicemail; a call with no transcript does not create a placeholder page.

Vapi can report an ended call before its transcript is ready. The existing call
state file retains up to ten pending completed-call contexts for 24 hours so a
later status check can save the original task and recipient. This also allows
retrying a failed Canvas save without blocking a new call. Saved contexts are
removed after Canvas saving and recording collection succeed, or expire after
24 hours; this state file does not retain transcripts.

### Files

| File | Purpose |
|------|---------|
| `skills/phone_call.py` | Main tool implementation |
| `lib/phone_call_artifacts.py` | Stash transcript/recording collection and Canvas association |
| `skills/phone_call.tool.json` | Tool definition for LLM |
| `docs/tools/phone/PHONE_CALLS.md` | This documentation |

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

1. **`extract_transcript()` function** - Checks the available sources for the best transcript:
   - `call['transcript']` and `call['artifact']['transcript']` - plain text
   - `call['messages']` and `call['artifact']['messages']` - message arrays

2. **Clear messaging** - The tool confirms a Canvas save only when it succeeds,
   so the model can distinguish saved results from a failed or pending save.

**If transcript seems missing:**
- Check Canvas `Phone Calls/` folder - it's likely there
- Browser refresh may be needed
- Async mode (`VAPI_WAIT_FOR_CALL=false`) saves on a later status check after the call ends

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

**Last Updated:** 2026-10-30
