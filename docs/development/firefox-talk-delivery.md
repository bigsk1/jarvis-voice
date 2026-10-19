# Firefox Talk implementation and testing

This maintainer reference covers the companion extension's Talk integration.
For installation, microphone setup, and controls, see
[Firefox Talk](../FIREFOX_TALK.md) and the
[extension README](../../jarvis-firefox-extension/README.md).

## Component responsibilities

- `ui/talk.js` owns the audio detector and session lifecycle inside the extension.
- `ui/talk-port.js` and `browser/talk.js` carry transient recording/playback data
  through authenticated background transport. Recordings are not saved in
  extension recovery storage.
- `core/client.js` owns ordinary request admission, recovery, and cancellation.
  Spoken turns add `input_mode: talk` and a caller-owned request identifier.
- `core/transport.js` reuses STT/TTS and same-server answer audio with bounded
  transfers, deadlines, and cancellation.
- `ui/panel.*` supplies controls. `ui/microphone.*` and
  `ui/microphone-client.js` support the sidebar's same-extension capture helper.

The server advertises the optional `extension.features.talk` capability through
`/api/status`. Ordinary chat can remain available against a server without Talk.
Only one extension view can own a Talk session. A competing task, including a
Completion Guard repair, pauses Talk until the user resumes it.

## Sidebar microphone behavior

The sidebar uses a same-extension Microphone setup tab because Firefox can leave
capture in the sidebar pending despite an existing permission grant.
Start/Resume briefly selects the helper to acquire a stream and restores the
previous tab when the user has not changed selection. The helper stays open in
the background during the conversation; closing it pauses Talk. Pop-outs and
full extension tabs use direct capture.

Microphone permission, add-on data consent, and host access are separate grants.
Tests that bypass native permission handling cannot establish that the sidebar
permission flow works. Preserve startup deadlines, resource release, cancellation
of pending startup, and handling of late permission grants.

## Automated checks

Run from the repository root:

```bash
npm --prefix jarvis-firefox-extension test

.venv/bin/python -m pytest \
  tests/test_web_socket_auth.py tests/test_web_talk.py \
  tests/test_web_talk_scope.py -q

./bin/test-suite
```

The extension suite and core regression suite are separate checks. The focused
backend tests use isolated state; JavaScript fixtures control audio, permission,
transport, ownership, and lifecycle edges. See the
[testing guide](../TESTING.md) for fixture and live-test boundaries.

## Browser and device checks

Use a disposable Firefox profile and an isolated Jarvis instance. Exercise the
actual sidebar and a pop-out, with normal permission checking enabled. Include
the Allow/Remember prompt, helper-tab capture, Pause/Resume/End, closing the
helper, a competing view, reconnect, and narrow viewports.

Synthetic audio can verify capture and transport. A physical microphone,
speakers/headphones, and first-time permissions are separate device checks.
Specify the Firefox/browser versions and platforms actually exercised; do not
infer Android or ESR support from a desktop test.

## Packaging

Source changes can be checked by temporarily loading `manifest.json`. Release
packaging and signing are separate from a source test. The version-bump and
build commands preserve existing artifacts; use the extension's
[review and packaging instructions](../../jarvis-firefox-extension/REVIEW.md)
for a distributable update.
