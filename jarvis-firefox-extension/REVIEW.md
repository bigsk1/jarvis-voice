# Unlisted signing and build guide

Jarvis Companion targets **unlisted signing and self-distribution**, for normal installation that survives Firefox restarts. It is a desktop client for the user's own [Jarvis Web server](https://github.com/bigsk1/jarvis-voice). A public AMO store listing and a hosted demonstration service are not part of this distribution plan. Passing local validation is not Mozilla signing or approval.

## Submit for unlisted signing

1. At the [AMO Developer Hub](https://addons.mozilla.org/developers/), submit a new add-on and choose **On your own**. For later versions, upload a new version under the same add-on.
2. Upload `web-ext-artifacts/jarvis_companion-VERSION.zip`, not the source archive. Select desktop Firefox platforms; Android is untested. Keep the existing ID `jarvis-companion@bigsk1.com`.
3. Supply the matching `jarvis_companion-VERSION-source.zip` if requested. First-party code is readable JavaScript; the only minified runtime library is the unmodified Socket.IO release described below. Include the build instructions and submission notes from this document where the form allows them.
4. After signing completes, download the **signed `.xpi`** from the version details in the Developer Hub. Renaming the unsigned ZIP is not signing. Do not edit or repack the signed file.
5. Install it through **Firefox → Add-ons and themes → gear menu → Install Add-on From File**. Approve installation. It remains installed after restarting Firefox; `about:debugging` is only for temporary development loading.

Follow Mozilla's [self-distribution submission steps](https://extensionworkshop.com/documentation/publish/submitting-an-add-on/#self-distribution) and [file installation guide](https://extensionworkshop.com/documentation/publish/install-self-distributed/). Unlisted submissions remain subject to Mozilla's policies and possible manual review. This project supplies source and setup instructions, not a hosted review account. If Mozilla requests additional testing access, that request requires a separate decision; unlisted signing does not guarantee an exemption.

## Publish a signed update

The extension's `update_url` is **https://raw.githubusercontent.com/bigsk1/jarvis-firefox-extension/main/updates.json**. Keep this address stable. It is a JSON update manifest, not the GitHub Releases webpage. Its update list stays empty until a signed XPI is available.

For each version, upload the unchanged Mozilla-signed XPI to a public GitHub Release with a unique version tag, such as `v0.2.2`. Then add an entry to the standalone repository's `updates.json` under `addons["jarvis-companion@bigsk1.com"].updates`:

```json
{
  "version": "VERSION",
  "update_link": "https://github.com/bigsk1/jarvis-firefox-extension/releases/download/vVERSION/SIGNED-FILENAME.xpi",
  "update_hash": "sha256:SHA256-OF-THE-SIGNED-XPI",
  "applications": {"gecko": {"strict_min_version": "140.0"}}
}
```

Replace the placeholders with the version and filename inside the signed file, its actual public download URL, and the SHA-256 of those signed bytes. The Jarvis Firefox publishing skill can prepare and validate this entry after the signed file is uploaded. Preserve older entries/assets and do not replace an existing version's bytes. The update feed is maintained only in the standalone repository, outside the source-export file set, so a later export cannot reset it.

Firefox can then discover higher signed versions through its normal update checks. Users can also choose **Check for Updates** in the Add-ons Manager. Merely uploading an XPI does not change `updates.json`, and a source-only GitHub commit must never advertise an unsigned package. See Mozilla's [update manifest format](https://extensionworkshop.com/documentation/manage/updating-your-extension/).

## Submission notes

The following describes this build for the developer form:

> Jarvis Companion is submitted for unlisted self-distribution on desktop Firefox 140+. It connects only to the Jarvis Web server configured by its user; no shared hosted service, review account, analytics, or author-operated backend is provided. Users supply their own server. Optional host access is requested for that server. Remote connections, including private LAN addresses, require HTTPS; explicitly enabled HTTP is restricted to loopback on the same computer.
>
> Chat, selected page content, and microphone audio are sent to the configured server only through the documented actions. Talk sends recorded speech after silence during an explicit session; its helper tab handles sidebar microphone acquisition. Server tools, speech/model providers, and retention are configured by the server owner. PRIVACY.md describes data and permissions.
>
> First-party JavaScript is not compiled or minified. The included Socket.IO client 4.7.2 bundle, source map with readable sources, and MIT license are copied unmodified from the official npm release by scripts/vendor.mjs. package.json and package-lock.json identify the public dependency. Reproduce using npm ci, npm run vendor, npm test, and npm run build. The two known linter warnings are documented below.
>
> Firefox's built-in add-on updater separately checks a public GitHub-hosted JSON manifest and downloads signed XPI files from GitHub Releases. No Jarvis credentials or conversation content are included in those update requests.

Official dependency: [socket.io-client 4.7.2 on npm](https://www.npmjs.com/package/socket.io-client/v/4.7.2). See Mozilla's [third-party library requirements](https://extensionworkshop.com/documentation/publish/third-party-library-usage/). Do not paste personal server addresses, credentials, or private conversations into public release notes.

## Reproduce a package

Use a fresh checkout of the exact standalone commit, or unpack the matching source archive, with Node.js 22 and npm. Local packaging was verified with Node 22.23.2 and npm 12.0.2 on Linux. CI uses Node 22 on Ubuntu.

```sh
npm ci
npm run vendor
npm test
npm run build
```

In a Git checkout, `git diff --exit-code -- vendor/` additionally confirms that copying the pinned vendor release did not alter the committed files. An unpacked source archive does not require Git.

The output is `web-ext-artifacts/jarvis_companion-VERSION.zip`, where VERSION matches `manifest.json`, `package.json`, and the root package-lock fields. The build runs `web-ext lint --self-hosted` for the unlisted distribution channel and refuses to overwrite an existing versioned ZIP. For a rebuild of the same version, use another fresh checkout. Compare extracted file contents; ZIP container timestamps may differ.

There is no application compilation, transpilation, or custom minification. `scripts/vendor.mjs` copies the unmodified Socket.IO client 4.7.2 release bundle, matching embedded-source map, and MIT license from the locked npm package. The installer excludes tests, build dependencies/scripts, CI, the external update feed, this guide, the changelog, and the README illustration. Runtime icons, privacy information, and licenses remain included.

For matching source from this standalone checkout:

```sh
git archive --format=zip --output=/tmp/jarvis-companion-source.zip HEAD
```

Retain the source commit, source archive, installer, version, and SHA-256 checksums together outside the source tree. Do not overwrite a published version. A GitHub link is useful for review, but does not replace any source attachment requested by AMO. Follow Mozilla's [source submission guide](https://extensionworkshop.com/documentation/publish/source-code-submission/) for the chosen package.

## Functional testing with an existing Jarvis server

These steps are for an operator who already has a Jarvis Web server with Companion API 1. Features `extension.features.text`, `profile`, and `talk`, plus configured STT/chat/TTS, enable their corresponding checks. The Web origin is commonly port 5001; FastAPI on 8880 is not the extension endpoint. No additional review deployment is provisioned by this workflow.

1. Install the signed XPI using the steps above. During source development only, temporarily load `manifest.json` through `about:debugging`. Use desktop Firefox 140 or newer and a normal, non-private browser window.
2. Open the toolbar sidebar. Enter your server's HTTPS origin, connect, grant that host access, and sign in if required. Send a short chat question and reopen it through History.
3. On a public test page, click the toolbar to grant temporary tab access. Capture the page, inspect the screenshot and full-text previews, then send. Unsent previews can be removed without uploading them.
4. Use **Include page**, grant optional tabs access, inspect the title/link, and send. Check the right-click selection, link, and image actions similarly. These stage content before sending.
5. For sidebar Talk, open **Settings → Microphone setup**, click **Allow microphone**, and remember Firefox's microphone decision. Keep this helper tab open. Start Talk with an empty draft, speak, and pause. Expect transcription, a chat response, spoken playback, then listening again. Start/Resume briefly selects the helper before restoring the previous tab. Check Pause, Resume, End, and closing the helper. Capture should stop during work/playback and after Pause/End. Repeat from the pop-out.
6. Enable optional desktop notifications in Settings, submit a short task, and switch away. Open its completion notification. Sign out and reconnect to check that saved results remain on the server.

The permission and data-flow explanations are in [PRIVACY.md](PRIVACY.md). Ordinary text chat does not automatically include the active tab. Talk explicitly sends speech after silence; leaving its helper tab open alone does not record. Server tools/providers and retention are controlled by that server.

## Before submitting to Mozilla

- Remote HTTP, including private LAN IPs, is rejected before connecting, including when restoring settings from an older version. The opt-in exception applies only to loopback on the same computer. Invalid TLS certificates are never bypassed.
- Review the current linter's two warnings: the official Socket.IO bundle has a `Function` fallback unused in Firefox and blocked by this extension's CSP; Firefox Android's built-in consent support begins after the desktop minimum. Android is untested. Neither warning is suppressed or proof of acceptance.
- Keep the submission notes, manifest consent categories, and privacy policy aligned with the separate server requirement, Talk's automatic speech submission, and actual data flow.
- Supply matching source/build instructions and the source-available license terms. Keep signing keys, AMO API credentials, server credentials, logs, and runtime data out of Git.

Publishing source does not sign or submit the extension. Automatic updates require a higher signed version advertised in `updates.json`; a GitHub source commit alone does not create one.
