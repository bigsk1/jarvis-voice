# Firefox Talk delivery

## Behavior and review map

The Firefox companion now offers the Web Talk conversation loop in its sidebar and pop-out: capture a bounded utterance, submit after silence, transcribe, run ordinary chat, play the answer, and listen again. Only one extension view can own Talk. Pause releases audio resources; Interrupt requests cancellation before another turn; closing a view stops capture while accepted work can finish in chat. A separate Completion Guard repair pauses Talk for explicit Resume.

- `ui/talk.js` contains the standalone audio detector and lifecycle controller. It has no dependency on files outside the extension package.
- `ui/talk-port.js` and `browser/talk.js` bridge transient recordings and playback buffers to authenticated background transport. Ownership, connection/mode/conversation identity, cancellation during admission, and late callbacks are checked at this boundary. Audio is never persisted in extension recovery storage.
- `core/client.js` preserves normal request admission, write-ahead recovery, and cancellation. Talk adds `input_mode: talk` and a caller-owned request ID; ending before admission retains the transcript without sending stale work.
- `core/transport.js` reuses STT/TTS and same-server answer audio with bounded sizes, deadlines, and cancellation. It rejects foreign audio URLs and redirects.
- `ui/panel.*` supplies inline controls and disables competing actions. `ui/microphone.*` supplies permission setup and the sidebar's native capture context; `ui/microphone-client.js` selects the same-extension helper in the sidebar's browser window. Recording, detection, playback, and session ownership remain in the sidebar.
- `/api/status` advertises optional `extension.features.talk`. Older servers still support ordinary extension chat, with Talk disabled. Existing casual formatting and configured mode/Web word limits apply; no settings are overwritten.

Firefox separates add-on/data consent, host access, and microphone permission. Existing grants are reused; optional notifications and tab access remain opt-in. Microphone permission cannot be included in the host permission request. Mozilla's voice-recording data category was added to the manifest and privacy disclosure. There is no broadening to automatic access to all sites.

## Validation — 2026-09-16

Validation scripts, logs, and screenshots are under `/tmp/jarvis-firefox-talk-validation/`. They are not runtime dependencies. The repo `.venv` was used for Python. Temporary harnesses redirect database, conversation, and Stash writes, copying SQLite only through read-only connections. A file-write guard rejects attempts to modify live state. Configured providers and real network requests remain in use.

- Extension `npm test`: **190 passed**, including ownership/admission races, lifecycle/resource cleanup, Completion Guard sequencing, permission failure, transport bounds, and ordinary UI/client regressions. This was run outside the sandbox: an earlier sandbox attempt prevented subprocess execution and was not counted as valid verification.
- Focused backend tests: **54 passed** in `test_web_socket_auth.py`, `test_web_talk.py`, and `test_web_talk_scope.py`.
- Full normal Python suite: **4,041 passed, 168 subtests passed**, in 158.22 seconds, with zero live-write guard violations. Command: `PYTHONPATH=/tmp/jarvis-firefox-talk-validation/regression timeout --signal=TERM --kill-after=10s 600s .venv/bin/python -m pytest tests -q -o faulthandler_timeout=60`.
- The first full-suite run passed 4,039 tests and reported two retention-test failures because a validation-wide `JARVIS_OVERRIDE_STASH_DIR` overrode their own temporary directories. Removing that unnecessary override made all six retention tests and the corrected full run pass. No application change was needed for those failures.
- JavaScript syntax and `git diff --check` passed. Ruff comparison against HEAD found no introduced diagnostics in the two modified Python files; their existing diagnostics were left unchanged.
- `npm run build`: packaged `web-ext-artifacts/jarvis_companion-0.1.6.zip`. Extension lint reported zero errors and two existing warnings concerning vendored Socket.IO and Android support for the data-consent manifest field. The development version was not bumped.

### Real Firefox and local services

Official Firefox **156.0** ran headlessly with a disposable profile. Marionette dependencies and the Firefox download lived under `/tmp`, without changing project dependencies. Automatic permission and fake-device preferences applied only to that test profile.

The modified Jarvis Web application ran on a temporary loopback port with normal authentication/configuration and isolated persistent destinations. Two synthetic spoken time questions passed through the extension's real MediaRecorder, silence detector, internal ports, STT HTTP upload, ordinary Socket.IO chat, configured local LLM/tools, and TTS decoding/playback. Both turns stayed in one conversation and returned to Listening. Pause, Resume, and End released microphone tracks and audio contexts.

The actual detached window passed native Firefox fake-device capture and Start/Pause/Resume/End checks. A second view could not start a competing microphone. Controls stayed within 320, 390, and 768px viewports without horizontal overflow. The actual Firefox sidebar also passed Start/Pause/End, and its screenshot was inspected. Sidebar controls were reached through Firefox's extension-view API after Marionette's nested-frame navigation proved unsuitable.

An early setup command tried to persist the selected mode to Web configuration; the write guard rejected it before any write. That unnecessary setup command was removed because the test server already started in local mode. Successful conversation and control runs caused no additional guard violations. Production processes were not restarted or used as evidence for changed code. No paid inference, deployment, commit, or push was performed for this extension change.

Temporary validation processes were stopped. Disposable database copies, conversations, Stash, authentication token, synthetic input, browser profiles, Firefox download, and automation dependencies were removed after verification. Logs, scripts, screenshots, and the development ZIP remain for review. Repeating browser validation requires preparing fresh temporary runtime/input/state.

## Operator check

Restart the updated Web process through the normal workflow, reload the development extension, reconnect, and follow [Firefox Talk](../FIREFOX_TALK.md). Test a physical microphone and the first-time Firefox permission prompt. These human/device checks, Firefox 140 ESR, paid cloud speech, and Android were not exercised. Synthetic audio verifies the integration, but not room acoustics or perceived speaker quality.

No migration, dependency update, or Tool RAG sync is required. Refresh the documentation index with `qmd update && qmd embed` when ready.

## Follow-up: sidebar microphone and version preservation — 0.2.0

The user's physical-device check exposed a missing validation boundary: the initial Firefox test disabled normal media permission handling. With permission checks enabled, Firefox 156.0 reproduced a pending native sidebar `getUserMedia()` promise both before and after a remembered grant, while the identical controller in a full extension tab reached Listening. Its AudioContext was already running. The helper was hidden until a rejection, so a promise that never settled also hid the recovery action.

Sidebar Talk now acquires its stream from the same extension's Microphone setup tab in the same browser window. Firefox also defers capture in an unselected normal tab, so Start/Resume briefly selects the helper, acquires capture, then restores the previous tab if the user has not selected a different one. The helper stays in the background during the conversation. Pause/End release the stream; closing the helper pauses Talk. It does not record merely because the tab is open. Full-page and pop-out clients keep direct capture.

Setup is available directly in Settings and in preparing/paused Talk. Microphone acquisition has a 30-second deadline; audio resume has an 8-second deadline. A suspended audio context cannot prevent the microphone request. Pause/End cancel startup waits, and late permission grants are stopped. Startup failures also produce a concise console warning.

Verification used a disposable Firefox 156.0 profile with a fake microphone, **normal permission checking enabled**, and the actual Firefox Allow/Remember prompt. The actual controller and helper were loaded in the real sidebar; only the chat/RPC state was isolated for this microphone-specific check. Native capture yielded nonzero signal (RMS about 0.07) and a 1,650-byte MediaRecorder chunk after the helper returned to the background. Pause/Resume released/reacquired capture and restored the previous tab. Closing the helper paused Talk and closed its AudioContext. These checks did not call speech/model services or modify production data. Logs and scripts: `/tmp/jarvis-firefox-sidebar-fix/`.

The extension suite passed **203 tests**. New cases cover suspended audio, never-settling microphone/audio promises, late grants, pausing during startup, helper lifecycle, preserving a user's tab selection, per-window helper selection, synchronized versions, and refusing artifact overwrite. Extension build/lint passed with the same two existing warnings described above. The backend was unchanged in this follow-up; its earlier full-suite result is recorded above.

The new package is **`jarvis_companion-0.2.0.zip`**. Checksums confirmed all seven existing 0.1.x ZIPs stayed unchanged. A second real build refused to overwrite 0.2.0. `npm run bump -- patch|minor|major` updates all extension version fields without committing or tagging; `npm run build` checks consistency and preserves prior artifacts. Future distributable changes require an appropriate version increment. Source-loading via `manifest.json` remains the development iteration path.
