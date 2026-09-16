# Web Talk delivery

## Objective and evidence

Deliver an explicit hands-free **Talk** session in Jarvis Web: start once, speak a question, let silence finish the turn, hear Jarvis, and continue in the same conversation. Keep the existing microphone button as editable dictation.

The clean-tree audit traced native wake-word → STT → orchestration/tools → TTS, Web source intake and conversation/run recovery, scoped config and provider routing, Tool RAG/memory/intelligence, schedules/notifications, and native/Docker boundaries. `ChatUI._processRecording()` currently appends transcripts to the draft and requires Send. `JarvisApp` plays answers but has no path back to listening. Native wake-word capture is host-only; Docker/browser users cannot use that loop. Configured STT/TTS services and provider-neutral chat already supply the required operations.

Compared with universal conditional monitors (partly served by scheduled workflows, release watches, price alerts and proactive alerts), Talk closes a direct gap in the application's core interaction. A new personal task registry would overlap existing reminders and schedules. No new model, provider, dependency, schema or deployment service is required. Recent commits/roadmap priority did not determine this decision.

## Acceptance criteria

- Separate, opt-in Talk control and visible state: preparing, listening, transcribing, waiting, speaking, paused/ended. Explain beside the control that speech is sent automatically.
- Speech activity and trailing silence create one bounded recording and exactly one ordinary chat request. Silence/no speech never sends. All turns stay in the selected conversation and mode, preserve the existing tool policy, and use normal tool progress/cancellation and saved history.
- Reuse configured STT and TTS. Apply concise response formatting only to Talk requests; never persist settings or change the ordinary dictation/text path. Reuse any already-generated answer audio.
- Microphone is inactive during transcription, model work and playback. Re-arm only after playback and authoritative task settlement. Explicit interruption stops playback and returns to listening; interrupting work cancels it and waits for terminal settlement before accepting another turn.
- Pause/end, Escape, navigation, mode switches, disconnect, hidden page and late permission/network/recorder callbacks cannot send stale speech, replay missed answers, or leave capture/playback resources running. No automatic microphone resume after reload/reconnect.
- Handle permission denial, unavailable/insecure browser APIs, device loss, STT/TTS failure, playback rejection and unavailable service clearly. Bounded idle and recording time; no silent retry loops.
- Responsive keyboard-accessible controls. Drafts and attachments are preserved; starting Talk with an unfinished draft gives an actionable message.
- Test state-machine race/failure paths, ordinary dictation/audio compatibility, server request-scope isolation, a real browser with synthetic audio, and configured local STT → modified chat/orchestrator → TTS with only write destinations isolated.

## Validation boundaries

Use the repository `.venv`. The first suite probe stopped import-time live MemoryDB initialization before writes. Subsequent checks redirect only default/live SQLite and conversation destinations into disposable targets and retain a fail-closed live-state file-write guard, real config and network access. Sandbox Unix-socket bind failures were reproduced and resolved through approved execution outside that sandbox. No paid inference, live database/index mutation, deployment, production restart, commit or push.

## Implementation and review map

- `jarvis-web/client/js/talk.js`: classic-script controller, bounded audio activity detection, explicit session ownership, stale-callback guards, speech requests/playback, cancellation and resource cleanup.
- `jarvis-web/client/js/chat.js` and `socket.js`: spoken turns use ordinary request IDs, admission, selected tool policy, draft recovery on rejection, and chat history.
- `jarvis-web/client/js/app.js`: one audio owner per response, including delayed ordinary TTS that started before Talk. Conversation navigation ends Talk.
- `jarvis-web/server/sockets/chat.py`: `input_mode=talk` installs existing casual formatting within that request's config scope. Word limits follow normal per-mode Web/environment precedence with existing defaults. Concurrent/next text requests retain their own preferences.
- `index.html` / `main.css`: separate Talk control, live status panel and responsive controls. User guide: [Web Talk](../WEB_TALK.md).
- `tests/test_web_talk.py`, `tests/js/web_talk_harness.cjs`, `tests/test_web_talk_scope.py`: real controller/composer/socket/app code with deterministic audio/network edges; real server admission/storage/scope with a fake LLM and temporary history.

Adversarial review corrected late ordinary TTS playback, competing conversation tasks, active-button contrast, hidden mobile controls, and task completion while Resume awaits microphone permission. Immediate restart checks also exposed a redundant end-session toast covering the mobile composer; explicit End/Escape now closes the panel without that toast. Pausing a submitted turn permanently silences that answer for the session, including a response arriving after Resume. Completion and playback must both finish before the next recording starts. Existing dictation stays draft-only.

## Validation record — 2026-09-15

All commands ran from the checkout using `.venv`. The validation-only hooks/scripts and detailed logs are under `/tmp/jarvis-next-feature-validation/`; they are not application dependencies. The hooks copy live SQLite through read-only connections and redirect only database/conversation write destinations. Real configuration, provider routing, tool manifests and services remain in use. A direct SQLite count helper initially hit the guard; its query was subsequently redirected to the same disposable snapshot. The completed runs below had zero guard violations.

```bash
# Baseline before Talk: 4003 passed, 168 subtests passed, 159.11s.
# The explicit plugin option emitted one harness-import warning.
PYTHONPATH=/tmp/jarvis-next-feature-validation timeout --signal=TERM --kill-after=10s 600s \
  .venv/bin/python -m pytest -p live_state_plugin tests -q -o faulthandler_timeout=60

# Initial delivery: 4035 passed, 168 subtests passed, 160.77s; no warnings.
PYTHONPATH=/tmp/jarvis-next-feature-validation timeout --signal=TERM --kill-after=10s 600s \
  .venv/bin/python -m pytest tests -q -o faulthandler_timeout=60

# Focused Talk scope/lifecycle/audio compatibility: 32 passed.
PYTHONPATH=/tmp/jarvis-next-feature-validation timeout 90s \
  .venv/bin/python -m pytest tests/test_web_talk.py tests/test_web_talk_scope.py -q

# Existing adjacent workflows: 68 passed.
PYTHONPATH=/tmp/jarvis-next-feature-validation timeout 180s \
  .venv/bin/python -m pytest tests/test_web_voice_dictation.py \
  tests/test_web_socket_reconnect.py tests/test_web_attachment_bundle_chat.py \
  tests/test_web_tts_audio_cleanup.py tests/test_web_status_tts_cache.py -q

.venv/bin/ruff check tests/test_web_talk.py tests/test_web_talk_scope.py
node --check jarvis-web/client/js/talk.js
node --check jarvis-web/client/js/chat.js
node --check jarvis-web/client/js/socket.js
node --check jarvis-web/client/js/app.js
node --check tests/js/web_talk_harness.cjs
git diff --check
```

All listed lint/syntax/diff checks passed. The modified backend file has 30 preexisting Ruff diagnostics; comparing against `git show HEAD:jarvis-web/server/sockets/chat.py` with the same Ruff configuration found no introduced diagnostics (allowing shifted line numbers). There were no baseline application test failures after correcting the validation destination/socket restrictions.

### Real services and browser

The actual modified Flask/Socket.IO Web application ran temporarily on loopback with its normal configuration and authentication. Only persistent destinations were isolated: copied Memory/Intelligence SQLite, disposable conversation JSON and temporary Stash. Existing production processes were not used as evidence for changed code.

Kokoro synthesized a harmless time question. FFmpeg converted it to a synthetic browser microphone WAV. Cached Chromium exercised real `getUserMedia`, AudioContext, MediaRecorder, silence detection, STT HTTP upload, ordinary Socket.IO chat, local Ollama (effective Web model `ornith:latest`), real embedding/hybrid Tool RAG, the read-only `get_time` tool, and Kokoro answer decoding/playback. Two spoken turns stayed in the same conversation and returned to Listening after each answer; Pause/End released capture and audio resources. The successful rerun had no JavaScript exceptions and no live-state guard violations. Desktop and 390px screenshots were inspected; the first pass found and prompted the mobile visibility fix.

The exact integration entry points were:

```bash
PYTHONPATH=/tmp/jarvis-next-feature-validation \
JARVIS_OVERRIDE_STASH_DIR=/tmp/jarvis-next-feature-validation/stash \
timeout 90s .venv/bin/python /tmp/jarvis-next-feature-validation/live_web.py --prepare

ffmpeg -nostdin -v error -y -i /tmp/jarvis-next-feature-validation/question.audio \
  -af 'adelay=1500,apad=pad_dur=12' -ar 48000 -ac 1 \
  /tmp/jarvis-next-feature-validation/microphone.wav

PYTHONPATH=/tmp/jarvis-next-feature-validation \
JARVIS_OVERRIDE_STASH_DIR=/tmp/jarvis-next-feature-validation/stash \
timeout --signal=TERM --kill-after=10s 600s \
  .venv/bin/python /tmp/jarvis-next-feature-validation/live_web.py

timeout --signal=TERM --kill-after=5s 180s \
  /home/boss/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome \
  --no-sandbox --headless=new --disable-dev-shm-usage --no-first-run \
  --no-default-browser-check \
  --user-data-dir=/tmp/jarvis-next-feature-validation/chrome-delivery \
  --remote-debugging-port=5098 --use-fake-ui-for-media-stream \
  --use-fake-device-for-media-stream \
  --use-file-for-fake-audio-capture=/tmp/jarvis-next-feature-validation/microphone.wav about:blank

timeout --signal=TERM --kill-after=5s 280s \
  .venv/bin/python /tmp/jarvis-next-feature-validation/browser_check.py
```

Chromium used a disposable profile, the generated fake microphone, headless mode, and debugging port 5098. Its host namespace restriction required an explicitly approved per-process `--no-sandbox`; no host security configuration changed. Browser and server subprocesses were time-limited. This is real-service validation with isolated writes and synthetic audio, not a physical microphone/speaker test or paid-cloud validation.

The final control-only browser check (`timeout 90s .venv/bin/python /tmp/jarvis-next-feature-validation/browser_check.py --controls-only`) passed actual Start/Pause/Escape and immediate restart, released tracks/contexts, text contrast and viewport bounds at 320, 390 and 768px without submitting inference. A programmatic-click probe helped distinguish event handling from the toast obstruction; the final passing verification uses hit testing and real browser mouse events. The documentation check (`PYTHONPATH=/tmp/jarvis-next-feature-validation timeout 60s .venv/bin/python -m pytest tests/test_docs_integrity.py -q`) passed all 4 tests.

Validation processes were stopped and disposable SQLite copies, conversations, Stash, browser profiles, authentication token and synthetic audio were removed after verification. Test logs, scripts and screenshots remain for review. Rerunning the browser check requires preparing its temporary audio and starting a fresh temporary server/browser again.

## Review status and remaining manual check

Implemented, covered by the full suite, and validated against real local services through the modified browser application. No migration, Tool RAG sync, dependency change, or settings change is required. Load the updated Web process and refresh the browser to use it; production has deliberately not been restarted.

Physical microphone acoustics, human-perceived playback, Safari/iOS and paid cloud speech were not exercised. Background-noise detection uses audio levels rather than a speech classifier, and interruption is explicit rather than speaking over Jarvis. Follow the five-step [manual check](../WEB_TALK.md#quick-check) after the normal Web restart/refresh.

## Follow-up: inherit configured word limits — 2026-09-16

Removed Talk's hard-coded 75-word overrides. It now overrides only response style to `casual`; normal per-mode Web/environment precedence supplies both word limits, with the existing defaults when absent. Regression checks reproduced six failures before the correction and passed afterward for cloud/local `.env` values, Web precedence, unset defaults, request isolation and concurrency. `PYTHONPATH=/tmp/jarvis-next-feature-validation timeout 90s .venv/bin/python -m pytest tests/test_web_talk.py tests/test_web_talk_scope.py tests/test_docs_integrity.py -q` passed **42 tests** (38 Talk plus 4 documentation). Ruff and `git diff --check` passed; zero live-write guard violations. The full-suite record above is from the initial delivery; this narrow follow-up used focused checks.
