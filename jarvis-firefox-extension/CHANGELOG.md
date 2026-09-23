# Changelog

## 0.4.0

- Save reviewed page text directly to the Cloud or Local Source Library without sending a chat message. The snapshot keeps the page URL and capture date and opens from the Firefox card.
- Capture again to preserve a later page version as a separate source. Image-only pages still need another text source; no screenshot OCR or automatic page refresh is performed.

## 0.3.0

- Display background task cards and late answers for the open conversation on compatible Jarvis Web servers. Restore saved task details from history and subscribe to authenticated task updates.
- Keep late results separate from the active chat request so they do not settle another turn, clear its progress, or interrupt Talk. Ignore duplicate answers and stale task revisions or conversation generations.
- Render task details as text. Background execution remains controlled by Jarvis Web Settings; Firefox chat and Talk keep their foreground execution behavior. No new permissions are requested.

## 0.2.2

- Prepare unlisted Mozilla signing and persistent installation from the signed XPI, with upload instructions and submission notes.
- Configure a stable GitHub-hosted update manifest for signed XPI downloads from GitHub Releases.
- Require HTTPS for every remote server, including private LAN addresses. The explicit HTTP opt-in now permits only loopback connections on the same computer. Existing LAN HTTP settings must be changed to HTTPS before reconnecting.
- Include Talk in the extension description. Preserve the extension ID and existing versioned packages.

## 0.2.1

- Prepare the standalone public source repository with automated test/build checks and Mozilla reviewer instructions.
- Exclude source-only documentation, CI files, and the README screenshot from the installable ZIP; retain runtime assets, privacy information, and licenses.
- Point extension issue reporting at the standalone repository. Talk behavior is unchanged.

## 0.2.0

- Add hands-free Talk to the sidebar and pop-out, using existing Jarvis STT/chat/TTS and configured word limits.
- Fix sidebar microphone startup with an explicit Microphone setup tab and bounded capture/audio waits. Setup is directly accessible in Settings. Pause, End, or closing the helper releases capture.
- Preserve existing versioned packages. Add synchronized patch/minor/major version bumps and reject builds that would overwrite an existing ZIP.

An earlier development build of Talk reused 0.1.6. Its ZIP is retained as produced; 0.2.0 is the separately versioned Talk update.
