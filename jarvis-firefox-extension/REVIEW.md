# Build and review guide

Jarvis Companion is a desktop Firefox client for a separately operated [Jarvis Web server](https://github.com/bigsk1/jarvis-voice). This repository contains the entire extension source, tests, locked development dependencies, and third-party notices. A successful build is not Mozilla approval or signing.

## Reproduce a package

Use a fresh checkout of the exact standalone commit for the submitted version, with Node.js 22 and npm. Local packaging was verified with Node 22.23.2 and npm 12.0.2 on Linux. CI uses Node 22 on Ubuntu.

```sh
npm ci
npm run vendor
git diff --exit-code -- vendor/
npm test
npm run build
```

The output is `web-ext-artifacts/jarvis_companion-VERSION.zip`, where VERSION matches `manifest.json`, `package.json`, and the root package-lock fields. The build runs `web-ext lint` and refuses to overwrite an existing versioned ZIP. For a rebuild of the same version, use another fresh checkout. Compare extracted file contents; ZIP container timestamps may differ.

There is no application compilation, transpilation, or custom minification. `scripts/vendor.mjs` copies the unmodified Socket.IO client 4.7.2 release bundle, matching embedded-source map, and MIT license from the locked npm package. The installer excludes tests, build dependencies/scripts, CI, this guide, the changelog, and the README illustration. Runtime icons, privacy information, and licenses remain included.

For matching source from this standalone checkout:

```sh
git archive --format=zip --output=/tmp/jarvis-companion-source.zip HEAD
```

Retain the source commit, source archive, installer, version, and SHA-256 checksums together outside the source tree. Do not overwrite a published version. A GitHub link is useful for review, but does not replace any source attachment requested by AMO. Follow Mozilla's [source submission guide](https://extensionworkshop.com/documentation/publish/source-code-submission/) for the chosen package.

## Functional testing

Provide the reviewer an accessible HTTPS Jarvis Web server with Companion API 1. Enable `extension.features.text`, `profile`, and `talk` to test those features, with working STT, chat, and TTS in the modes offered. Supply the exact tested server revision and enabled capabilities in the submission notes. The Web origin is commonly port 5001; FastAPI on 8880 is not the extension endpoint.

Use a dedicated review deployment with test content and tools suitable for reviewer actions. Supply its origin and any required login credentials privately in AMO reviewer notes, never in this repository. Mozilla requires [testing instructions and credentials where needed](https://extensionworkshop.com/documentation/publish/add-on-policies/#submission-guidelines).

1. Load `manifest.json` or the unsigned ZIP through Firefox's `about:debugging` temporary add-on loader. Use desktop Firefox 140 or newer and a normal, non-private browser window.
2. Open the toolbar sidebar. Enter the review server's HTTPS origin, connect, grant that host access, and sign in if required. Send a short chat question and reopen it through History.
3. On a public test page, click the toolbar to grant temporary tab access. Capture the page, inspect the screenshot and full-text previews, then send. Unsent previews can be removed without uploading them.
4. Use **Include page**, grant optional tabs access, inspect the title/link, and send. Check the right-click selection, link, and image actions similarly. These stage content before sending.
5. For sidebar Talk, open **Settings → Microphone setup**, click **Allow microphone**, and remember Firefox's microphone decision. Keep this helper tab open. Start Talk with an empty draft, speak, and pause. Expect transcription, a chat response, spoken playback, then listening again. Start/Resume briefly selects the helper before restoring the previous tab. Check Pause, Resume, End, and closing the helper. Capture should stop during work/playback and after Pause/End. Repeat from the pop-out.
6. Enable optional desktop notifications in Settings, submit a short task, and switch away. Open its completion notification. Sign out and reconnect to check that saved results remain on the server.

The permission and data-flow explanations are in [PRIVACY.md](PRIVACY.md). Ordinary text chat does not automatically include the active tab. Talk explicitly sends speech after silence; leaving its helper tab open alone does not record. Server tools/providers and retention are controlled by that server.

## Before submitting to Mozilla

- Resolve the development HTTP exception: the current UI permits explicitly opted-in localhost **and private-LAN HTTP**. Mozilla's [development practices](https://extensionworkshop.com/documentation/publish/add-on-policies/#development-practices) require encryption for remote data. Private-LAN HTTP is a potential conflict; disclosure alone does not establish acceptance. Use HTTPS for review and settle this behavior before submission.
- Review the current linter's two warnings: the official Socket.IO bundle has a `Function` fallback unused in Firefox and blocked by this extension's CSP; Firefox Android's built-in consent support begins after the desktop minimum. Android is untested. Neither warning is suppressed or proof of acceptance.
- Confirm the listing explains the separate Jarvis server requirement, Talk's automatic speech submission, and transmission to that server and its configured providers. Keep the manifest consent categories and privacy policy aligned with actual behavior.
- Provide working reviewer access, matching versioned source/build instructions when requested, and the source-available license terms. Keep signing keys, AMO API credentials, server credentials, logs, and runtime data out of Git.

Publishing this repository does not sign the extension, submit it to AMO, create a hosted service, or enable automatic browser updates. Those are separate distribution steps.
