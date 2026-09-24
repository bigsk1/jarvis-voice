# Hands-free Talk in Jarvis Web

Click **Talk** beside the message input, allow microphone access, and speak a question.
After a short pause, Jarvis sends the transcript, answers aloud, and listens for
your next question in the same conversation. The transcript and reply appear in
ordinary chat history, including tool results and progress.

Talk is separate from the microphone button, which records an editable draft.
Talk sends speech automatically. Finish or clear an existing draft or attachment
before starting. The Talk button is also available in the mobile composer.

## Controls

- **Pause** releases the microphone and stops playback. A submitted task can
  finish in chat. **Resume** starts listening again without replaying its answer.
- **Interrupt to speak** stops the current answer. If Jarvis is still working,
  it requests cancellation and waits for that task to settle before listening.
- **End Talk**, **Esc**, or the Talk button ends the session and requests
  cancellation of any unfinished Talk task. This cannot undo completed actions.
- Say **“end talk”**, **“stop listening”**, or **“goodbye”** as a complete utterance
  while listening to end the session without sending that utterance to chat.

The panel always shows whether Jarvis is listening, transcribing, working,
speaking, or paused. The microphone track is disabled while transcribing,
working, and speaking. Use Interrupt to cut in; speaking over playback does not
trigger another request.

When a Web tool requires approval, Talk pauses with the microphone off and shows
**Allow once** and **Don't run** in the Talk panel. Choose one there or in the
chat approval card. **Don't run** stops that tool sequence and leaves completed
results in chat for follow-up; **Allow once** runs only the pending call. Ending
Talk or pressing Stop while approval is pending cancels the turn. A new request
can propose the tool again and asks for a new approval.
Talk speaks the declined or expired approval reply, then resumes listening. Stop
pauses Talk as before.

Changing conversations, hiding the page, or losing the connection ends capture
and playback. Already submitted work may finish in chat and can be recovered
through [task recovery](WEB_TASK_RECOVERY.md). Starting a new chat or changing
mode requests cancellation of the current Talk task. Reloading or reconnecting
never restarts the microphone automatically. If another task starts in the same
conversation, Talk pauses until you resume it.

## Providers and configuration

Talk uses the selected local/cloud mode, configured STT and TTS providers, and
ordinary Web model and tool settings. Selected tool hints and **Chat only** remain
effective. It works with a browser connected to native or Docker Jarvis; the
microphone belongs to the browser device, not the server.

No new settings, models, dependencies, or database migrations are needed. Both
speech services must already work in the selected mode. Talk plays its own
answers even when ordinary chat audio is off, suppresses competing status/answer
audio, and leaves the audio toggle unchanged. It reuses server-generated answer
audio when present. Talk requests use the existing `casual` response formatter
with the selected mode's `JARVIS_QA_WORD_LIMIT` and `JARVIS_MULTI_TURN_WORD_LIMIT`.
Saved per-mode Web word limits take precedence over the mode's `.env` values;
the normal defaults are 75 words each when no value is configured. These are
formatting targets, and direct tool speech or formatting fallbacks may be longer.
Ordinary text responses keep your saved formatting preferences.

The browser requires microphone access, MediaRecorder, and Web Audio. Use HTTPS
or localhost; remote plain HTTP generally does not expose microphone APIs.
Browser requirements are documented in
[MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
and [Web Audio guidance](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices).

## Limits and troubleshooting

- A turn ends after about 1.2 seconds of silence, or 45 seconds of recording.
  Thirty seconds without sustained sound pauses Talk. The detector measures
  audio level; steady loud background noise can be mistaken for speech.
- Recordings are bounded to 10 MB. STT/TTS browser requests have a 90-second
  deadline. Service errors pause the session and leave completed replies in chat.
  Resume explicitly after correcting the cause; there is no automatic retry loop.
- If microphone access is denied, allow it in the browser and press Resume. If
  playback is suspended or the input device disconnects, the panel explains how
  to resume. Close an unanswered permission prompt yourself after ending Talk;
  late permission grants are discarded and their tracks stopped.
- Raw microphone clips use the existing temporary STT upload path and are removed
  after transcription. Talk does not archive recordings. Transcripts and answers
  follow ordinary chat persistence. Aborting a browser speech request cannot undo
  processing already underway at the configured service.

## Quick check

1. Load the updated Web server and refresh the browser. Select the intended mode.
2. With an empty composer, click Talk and ask “What time is it in UTC?” Let the
   pause send it. Check the transcript, tool result, spoken answer, then Listening.
3. Ask a follow-up. Confirm both turns appear in the same conversation.
4. Try Pause/Resume, Interrupt during an answer, and End Talk. Check the browser's
   microphone indicator clears after Pause/End. Reload: Talk must stay off.
5. Try the ordinary microphone button or type a message. Dictation should still
   require Send, and ordinary audio/formatting preferences should be unchanged.
