# Jarvis Companion privacy information

Jarvis Companion is a client for the Jarvis Web server you configure. The extension does not operate its own cloud service, include analytics, or send telemetry to its author.

Firefox's built-in add-on updater separately checks the public `updates.json` file on `raw.githubusercontent.com/bigsk1/jarvis-firefox-extension/main/` and downloads advertised signed XPI files from GitHub Releases. These requests expose ordinary network metadata to GitHub; the extension does not attach Jarvis credentials, speech, messages, or page content to them. Manage automatic extension updates through Firefox's Add-ons Manager.

## What is transmitted

When you connect, the extension checks server status and capabilities. Signing in sends your Jarvis Web password to that server's login endpoint. Subsequent authenticated REST requests use a Bearer token; Socket.IO supplies the token in its authentication handshake, not in a URL.

If supported, the extension retrieves your saved display name and avatar from that same server after connecting and when the server reports a profile change. These are displayed on your messages and held in memory, omitted from recovery storage, and cleared on sign-out or server changes. Avatar pixels arrive in the authenticated response; the panel does not fetch an external avatar URL. Edit or remove the image in Jarvis Web **Settings → Profile → Appearance**.

When you choose **Send**, **Analyze page**, or **Analyze screenshot**, the extension can transmit:

- The message you composed or the displayed action's default question.
- The staged screenshot, resized to JPEG with a maximum edge of 1,024 pixels at quality 0.85.
- The staged page text as a UTF-8 Markdown note, truncated to Jarvis Web's existing 100KB text-upload limit. Password fields, form inputs, contenteditable drafts, CSS-hidden nodes, scripts, and other tabs are not included. **Review full text** shows the exact Markdown before Send.
- The selected text, link, or image URL you explicitly staged and left in the message.
- The page title and URL shown in the removable **Include page** card, if present.
- Source page titles, URLs, and capture time included with that content.
- Conversation/request identifiers and the selected Jarvis cloud/local mode.

**Talk sends speech automatically while listening.** After you start Talk and allow the microphone, a short silence submits the recorded clip to the configured Jarvis server's STT endpoint. The transcript goes through ordinary chat and the reply through the configured TTS provider. These providers can be local or remote, according to your server's selected mode and configuration. Raw clips and returned playback buffers are held only in memory by the extension; the Web STT route uses a temporary file and removes it after transcription. Transcripts and replies follow ordinary chat retention. The extension does not record audio outside an explicit Talk session, and it does not capture system/tab audio.

Pause/End release the microphone and stop playback. Capture is disabled while transcribing, working, or speaking. Closing/hiding the owning view or disconnecting ends Talk; microphone capture never resumes automatically after reload. The microphone helper's permission check immediately stops its test stream and uploads nothing. During an explicit sidebar Talk session, the helper tab opens the microphone and shares its stream only with the sidebar from the same extension. It briefly selects its own tab for capture permission, then restores the previous tab unless you selected another one. It must stay open for sidebar Talk; closing it releases capture and pauses Talk. Merely leaving the helper open does not record audio. Aborting a request cannot undo processing already started by a speech provider.

Connection recovery, opening history, and background completion checks can retrieve saved conversations without another Send action. While extension-submitted requests are pending, checks run about once a minute even with the sidebar/pop-out closed, provided Firefox is running and the session is available. They stop when requests settle, expire after seven days, or the session ends. They only check existing work and never resubmit it. Normal HTTP/socket communication also exposes network information such as your address to the server. The extension does not continuously capture tabs, read browsing history, inject a persistent page script, or upload a screenshot or page text merely because its preview is visible. Page-text reading uses a one-shot script after a capture gesture.

Image URL staging does not fetch the image or copy the webpage's cookies. After Send, Jarvis's normal tool path can fetch that URL. An `analyze_image` tool hint accompanies an applicable staged image draft; server configuration determines which tools can run.

**Include page** reads only the selected tab's title and URL after your click. It does not capture pixels, execute a page script, fetch the link, or send anything to Jarvis until Send. The staged link stays fixed across navigation and tab changes. A YouTube video link adds a `youtube_transcript` tool preference for normal chat; the server controls available tools and their providers. Ordinary chat does not automatically include a tab link.

Firefox's declared data categories are `authenticationInfo`, `personalCommunications`, `websiteContent`, `browsingActivity`, and `personallyIdentifyingInfo` (which Mozilla's taxonomy includes for voice recordings). Transmission to a user-owned Jarvis server is still transmission. The extension does not declare or implement optional analytics collection.

## What stays in Firefox

| Storage | Contents | Lifetime |
| --- | --- | --- |
| `storage.local` | Server URL, connection preferences, and completion-notification preferences | Until changed or extension data is removed. |
| `storage.session` | Login token, bounded chat/recovery state, source metadata, unsent draft/attachment, and completion IDs/unread/deduplication state | In memory during the extension session; cleared when Firefox exits or the extension is disabled/reloaded. |

The extension does not persist your password, put credentials in page scripts or URLs, use synchronized extension storage, or save the token in `storage.local`. An open sidebar or pop-out exchanges a small local ping/pong with the background every ten seconds; it contains no page data or credentials and is not transmitted to the server. Closing the view stops its timer. Session storage is not an encrypted credential vault. Password-manager behavior and operating-system memory handling are controlled by Firefox and your system.

Closing the pop-out does not erase the session or cancel an accepted Jarvis request. Logging out removes the extension's token; the current Jarvis server token model does not individually revoke that token. Sign in again to recover previously accepted work.

The toolbar badge is enabled by default. Desktop notifications and answer previews are disabled by default. Enabling desktop notifications requests Firefox permission; their default text does not include page URLs or answer content. Enabling answer previews allows a bounded excerpt to appear in operating-system notifications, potentially on the lock screen or in notification history. Turning a setting off affects future alerts; notification history retained by the operating system is outside the extension's control. Completion bookkeeping is scoped to the configured server and sign-in session and contains no separate copy of answer previews or credentials.

## Permissions

- **`activeTab`:** temporary access after a toolbar or context-menu action, used for the selected webpage, visible capture, and one-shot page-text read.
- **`scripting`:** run that one-shot page-text reader in the selected tab after the capture gesture. No persistent content script is registered.
- **`menus`:** Jarvis actions for page capture, selected text, links, and image URLs.
- **`storage`:** settings and session recovery.
- **`alarms`:** wake the background for saved-request checks while extension-submitted work is pending.
- **Optional `notifications`:** requested only when you enable desktop completion notifications.
- **Optional `tabs`:** requested by **Include page** so the sidebar can read tab titles and URLs without another toolbar click. Firefox grants access to tab metadata; this extension only stages the selected page when asked. This does not grant access to page contents or screenshots. Revoke it in Firefox's extension permissions; toolbar/context-menu temporary access remains available.
- **Optional host access:** requested for the server you enter in settings. Firefox host match patterns cover the host rather than a single port; the extension still directs requests to the exact configured origin.
- **Microphone:** Firefox's separate `getUserMedia` prompt, requested when starting or resuming Talk or explicitly checking permission. This is independent of server host access. Keep the remembered grant to avoid repeated prompts; revoke microphone access through Firefox when needed.

The extension declares optional HTTP(S) host patterns so users can enter their own server. This is not a blanket grant at installation. It does not request access to every visited site. Private browsing is disabled, and capture also rejects private tabs and browser/extension pages.

## Transport and server retention

Use HTTPS/WSS for encrypted transport to every remote server, including private LAN addresses. A clearly labeled setting permits unencrypted HTTP only for loopback connections on the same computer (`localhost`, its subdomains, `127.0.0.0/8`, or `::1`). This exception does not permit private-LAN, link-local, or other remote IP addresses. The extension does not bypass invalid TLS certificates.

After upload, content follows your Jarvis server's normal processing and retention rules. In the current Web implementation, uploaded screenshots are written to disk, page text is stored as a Web text attachment, image processing can copy screenshots into Stash and record memory references, and chat saves conversations and answers. Tools, logs, and configured model providers can retain additional records according to their own configuration and policies. A user-owned server can still send data onward to cloud model or tool providers; selecting local mode is not an extension-level guarantee that every enabled tool is local.

There is no server-side ephemeral/private-chat mode in this extension. Removing an unsent preview prevents its upload. Removing a sent preview, clearing local extension state, logging out, or uninstalling does not remove content already held by Jarvis or its providers. Use the server's conversation, Stash, memory, and retention controls for those records; consult the server operator when you do not control that deployment.

## Controls and contact

You choose the server, when to capture, what to stage, and when to send. **Stop** requests cancellation of current work; completed tool actions and existing saved records are not undone. Reconnection looks up existing requests and never automatically resends uncertain work.

Change or revoke server access in Firefox's extension permissions. Report extension issues through the [extension repository](https://github.com/bigsk1/jarvis-firefox-extension/issues); do not include passwords, tokens, private conversations, or other sensitive data in a public issue. For data held by a configured server or provider, contact that server's operator or provider.
