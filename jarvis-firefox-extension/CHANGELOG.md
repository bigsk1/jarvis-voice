# Changelog

## 0.2.1

- Prepare the standalone public source repository with automated test/build checks and Mozilla reviewer instructions.
- Exclude source-only documentation, CI files, and the README screenshot from the installable ZIP; retain runtime assets, privacy information, and licenses.
- Point extension issue reporting at the standalone repository. Talk behavior is unchanged.

## 0.2.0

- Add hands-free Talk to the sidebar and pop-out, using existing Jarvis STT/chat/TTS and configured word limits.
- Fix sidebar microphone startup with an explicit Microphone setup tab and bounded capture/audio waits. Setup is directly accessible in Settings. Pause, End, or closing the helper releases capture.
- Preserve existing versioned packages. Add synchronized patch/minor/major version bumps and reject builds that would overwrite an existing ZIP.

An earlier development build of Talk reused 0.1.6. Its ZIP is retained as produced; 0.2.0 is the separately versioned Talk update.
