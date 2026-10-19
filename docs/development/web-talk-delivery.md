# Web Talk implementation and testing

This maintainer reference describes the Web Talk integration and how to check
changes. For setup, controls, and microphone requirements, use the
[Web Talk guide](../WEB_TALK.md).

## Component responsibilities

- `jarvis-web/client/js/talk.js` owns the Talk lifecycle, audio activity detection,
  microphone resources, turn submission, interruption, and playback sequencing.
- `chat.js` and `socket.js` connect spoken turns to ordinary request IDs, tool
  policy, admission, cancellation, history, and draft recovery.
- `app.js` coordinates answer audio and conversation navigation.
- `jarvis-web/server/sockets/chat.py` handles `input_mode=talk` within the
  request's configuration scope. Talk uses casual formatting; word limits follow
  the selected mode's normal Web/environment precedence.
- `index.html` and `main.css` provide the Talk controls and status panel. The
  existing microphone button remains editable dictation.

Talk reuses the configured STT/TTS endpoints and ordinary chat orchestration.
Its controls and microphone state belong to the browser session; reconnecting
must not start capture or replay a saved answer.

## Behaviors to preserve

- A spoken turn stays in the selected conversation and mode and follows the
  same tool policy as text chat.
- Speech activity followed by the configured silence submits one bounded
  recording. Silence alone does not create a chat turn.
- Pause and End release capture/playback resources. Late permission, recorder,
  or network callbacks must not revive an ended session.
- The next spoken turn waits for authoritative task settlement. Interrupting a
  request cannot undo tool actions that have already completed.
- Speak to interrupt is opt-in. The manual Interrupt control remains available
  when browser audio requirements are unavailable.
- A text request after Talk retains its own response-style configuration.
- Conversation navigation, mode changes, disconnects, and competing work must
  not leave a microphone or stale submission active.

The [user guide](../WEB_TALK.md) describes current controls and browser limitations.

## Automated checks

From the repository root:

```bash
.venv/bin/python -m pytest \
  tests/test_web_talk.py tests/test_web_talk_scope.py \
  tests/test_web_voice_dictation.py tests/test_web_tts_audio_cleanup.py -q

node --check jarvis-web/client/js/talk.js
./bin/test-suite
```

The focused tests exercise shipped browser code with controlled audio/network
boundaries and server handlers with temporary state and scripted model results.
They protect lifecycle, request-scope, and ordinary dictation compatibility.
They do not establish physical microphone quality or support on every browser.
See the [testing guide](../TESTING.md) for environments and fixture permissions.

## Browser and device checks

Use a separate test instance with disposable configuration, databases,
conversations, and Stash for end-to-end work. Configured speech or chat services
can incur costs and produce normal application state; choose them explicitly.
Do not depend on a previous session's temporary scripts, ports, or browser profile.

Follow the [manual check](../WEB_TALK.md#quick-check) with the browsers and devices
being supported. Include first-time permission, a follow-up turn, Pause/Resume,
Interrupt/End, navigation, reconnect, and competing answer audio. Test narrow
viewports and actual pointer/keyboard interaction. Synthetic audio helps verify
integration paths; a physical microphone and speakers/headphones are needed to
assess acoustics, echo, and perceived playback.
