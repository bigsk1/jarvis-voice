# Jarvis Companion for Firefox

A Firefox client for [Jarvis Voice](https://github.com/bigsk1/jarvis-voice): chat in a sidebar or detached window, capture a webpage, and ask follow-up questions without saving screenshots by hand.

This is an independently versioned development extension. It lives in `jarvis-firefox-extension/` for now and can be copied into its own repository without importing code from the parent checkout.

## What it does

- Opens the Jarvis sidebar from the toolbar, with an **Open pop-out** button for a detached window.
- Stages a visible-tab screenshot with a preview, source title, URL, and capture time.
- Sends your question or an **Analyze screenshot** prompt through your Jarvis Web server.
- Provides right-click **Jarvis** actions for a screenshot, selected text, or a link.
- Shows task and tool progress, completed answers, conversation history with pinned labels, and **Stop**.
- Reconnects to accepted work by its request/conversation ID without automatically sending the question again.

Chat uses the tools enabled by the connected Jarvis server. Dedicated Intel, Stash, workflow, media, and voice screens are not part of this first version. Intermediate tool events missed during a disconnect cannot all be replayed; saved answers and current run status are recovered.

## Requirements

- Firefox **140 or newer**.
- A reachable **Jarvis Web** server with Companion API **1** and socket authentication support. Use the Web chat server address, commonly port `5001`, rather than the separate FastAPI server on `8880`.
- Node.js **22 or newer** and npm to install development dependencies or build the package.

The extension checks `/api/status` for the capability contract and rejects older servers before sending chat content. The contract is independent of the extension and Jarvis release numbers. Restart an updated Jarvis Web server before testing the extension against new server code.

## Load it temporarily

From this directory:

```sh
npm ci
npm run vendor
```

In Firefox, open `about:debugging`, choose **This Firefox → Load Temporary Add-on**, and select this directory's `manifest.json`. After editing files, use **Reload** on that debugging page.

Temporary add-ons are removed when Firefox restarts. Reloading or removing the add-on can also clear its session state; sign in again if requested. This workflow is for local testing and does not produce a permanently installed unsigned extension.

For a distributable development ZIP:

```sh
npm test
npm run lint
npm run build
```

The ZIP and a short installation note are written to `web-ext-artifacts/`. Firefox's temporary add-on loader also accepts the ZIP. Regular persistent installation requires Mozilla signing; an unlisted signed release can be distributed without a public AMO listing. Passing local checks does not guarantee Mozilla approval. See Mozilla's [temporary installation guide](https://extensionworkshop.com/documentation/develop/temporary-installation-in-firefox/) and [signing overview](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/).

Current `web-ext` reports two warnings: the unmodified Socket.IO 4.7.2 bundle contains a `Function` fallback for environments without `self`/`window` (unused in Firefox, and blocked by this extension's CSP), and the desktop Firefox 140 minimum predates Android's built-in data consent support. This version targets desktop Firefox; Android support is untested. Neither warning is suppressed. Keep the pinned library source and lockfile available for review.

## Connect and capture

1. Open the webpage you want to discuss and click the Jarvis toolbar icon. This grants temporary tab access and opens the sidebar. Its **Open pop-out** button keeps the detached window available.
2. In **Connection settings**, enter the full Web server origin, such as `https://jarvis.example.com`, including a port when needed. Omit `/api` and other paths.
3. Click **Connect** and grant Firefox access to that server. If Jarvis authentication is enabled, enter the existing **Jarvis Web password** and sign in. Servers with authentication disabled do not require a password.
4. Click **Capture browser view**. Review the screenshot, enter a question, then **Send**. **Analyze screenshot** sends the displayed capture with its default question.
5. After changing the webpage or switching tabs, use **Capture again** and ask “Check it now.” Each click selects the currently active tab in that sidebar's window. The pop-out selects the most recently used normal browser window. If Firefox requests tab access, click the Jarvis toolbar icon on that webpage and retry.

Right-click selected text or a link to stage that content in the same composer. These actions do not fetch the page or send its contents until you choose **Send**. Screenshots are also kept locally until Send/Analyze; removing an unsent attachment prevents its upload.

Capture covers the **visible webpage viewport**, not the full scrolling page, Firefox browser chrome, another application, or the desktop. The selected tab must remain active in its normal, restored browser window. Jarvis checks the tab ID, window ID, URL, and window state before and after capture; it refuses a source that changes during capture. Minimized windows, private browsing, and non-HTTP(S) pages are unsupported.

Screenshots are resized locally to a maximum **1,024 pixels on the longest edge**, preserving aspect ratio without upscaling, and encoded as JPEG at quality **0.85**. The server keeps its existing resize safeguard. This limit is intentional for Jarvis's image/provider transport. There is no continuous screen sharing or background screenshot collection.

## Connection and privacy

HTTPS/WSS is the default. **Allow HTTP for a local development server** enables an explicit exception for localhost or a private IP, for example `http://192.168.1.20:5001`. HTTP does not encrypt passwords, tokens, messages, or screenshots. Public HTTP endpoints are refused; an invalid HTTPS certificate is not bypassed.

The server address and preferences use `storage.local`. The login token and bounded recovery/draft state use in-memory `storage.session`; the extension does not persist the password, save the token to disk storage, or synchronize it. Expect to sign in after Firefox restarts. Logout clears the extension credential but does not revoke the server's existing stateless token or cancel already accepted work.

**Jarvis stores submitted content.** Image upload writes to the server, and the normal chat path can preserve screenshots in Stash and memory as well as save conversation history. Your server may forward content to its configured model and tool providers. Removing an attachment after sending, logging out, or uninstalling the extension does not delete those server records. Read [PRIVACY.md](PRIVACY.md) before connecting to a server you do not operate.

## Development

| Command | Purpose |
| --- | --- |
| `npm ci` | Install the pinned development dependencies. |
| `npm run vendor` | Copy the unmodified Socket.IO client, matching source map, and license into `vendor/`. |
| `npm test` | Run the Node test suite. |
| `npm run lint` | Check the extension package with `web-ext`. |
| `npm run build` | Lint and produce the unsigned development ZIP. |

The background event page owns the client and connection. While a sidebar or pop-out is open, a small ping/pong every ten seconds prevents Firefox's idle event-page suspension. These messages stay inside the extension and do not copy screenshots, write storage, or call Jarvis. Closing the view stops its timer. Firefox may then unload the background; recovery state lives in `storage.session`, while actual run ownership stays on the server. Reopening recovers accepted work without sending it again.

```text
background.js   Browser lifecycle, view messages, and action wiring
core/           Authentication, server transport, client state, and recovery
browser/        Source selection, screenshot preparation, and context menus
ui/             Sidebar, pop-out, connection settings, and rendering
assets/         Packaged icons and styling assets
vendor/         Pinned third-party runtime code and its license
tests/          Browser, client, UI, and packaging checks
scripts/        Vendor copying and package creation
```

Keep new feature screens behind the client/capability contract. Do not import files from `../jarvis-web/` or load executable libraries from a CDN. Keep this directory as the authoritative source until a deliberate repository extraction; copying to another repository does not establish automatic synchronization.

## License

Copyright © 2024–2026 BigSk1. This extension uses the parent project's [Source Available License](LICENSE), including attribution and non-commercial restrictions. See the original [Jarvis Voice repository](https://github.com/bigsk1/jarvis-voice). Vendored dependencies retain their own accompanying licenses.
