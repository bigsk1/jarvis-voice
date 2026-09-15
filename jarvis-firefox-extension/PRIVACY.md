# Jarvis Companion privacy information

Jarvis Companion is a client for the Jarvis Web server you configure. The extension does not operate its own cloud service, include analytics, or send telemetry to its author.

## What is transmitted

When you connect, the extension checks server status and capabilities. Signing in sends your Jarvis Web password to that server's login endpoint. Subsequent authenticated REST requests use a Bearer token; Socket.IO supplies the token in its authentication handshake, not in a URL.

If supported, the extension retrieves your saved display name and avatar from that same server after connecting and when the server reports a profile change. These are displayed on your messages and held in memory, omitted from recovery storage, and cleared on sign-out or server changes. Avatar pixels arrive in the authenticated response; the panel does not fetch an external avatar URL. Edit or remove the image in Jarvis Web **Settings → Profile → Appearance**.

When you choose **Send**, **Analyze page**, or **Analyze screenshot**, the extension can transmit:

- The message you composed or the displayed action's default question.
- The staged screenshot, resized to JPEG with a maximum edge of 1,024 pixels at quality 0.85.
- The staged page text as a UTF-8 Markdown note, truncated to Jarvis Web's existing 100KB text-upload limit. Password fields, form inputs, contenteditable drafts, CSS-hidden nodes, scripts, and other tabs are not included. **Review full text** shows the exact Markdown before Send.
- The selected text, link, or image URL you explicitly staged and left in the message.
- Source page titles, URLs, and capture time included with that content.
- Conversation/request identifiers and the selected Jarvis cloud/local mode.

Connection recovery, opening history, and background completion checks can retrieve saved conversations without another Send action. While extension-submitted requests are pending, checks run about once a minute even with the sidebar/pop-out closed, provided Firefox is running and the session is available. They stop when requests settle, expire after seven days, or the session ends. They only check existing work and never resubmit it. Normal HTTP/socket communication also exposes network information such as your address to the server. The extension does not continuously capture tabs, read browsing history, inject a persistent page script, or upload a screenshot or page text merely because its preview is visible. Page-text reading uses a one-shot script after a capture gesture.

Image URL staging does not fetch the image or copy the webpage's cookies. After Send, Jarvis's normal tool path can fetch that URL. An `analyze_image` tool hint accompanies an applicable staged image draft; server configuration determines which tools can run.

Firefox's declared data categories are `authenticationInfo`, `personalCommunications`, `websiteContent`, and `browsingActivity`. Transmission to a user-owned Jarvis server is still transmission. The extension does not declare or implement optional analytics collection.

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
- **Optional host access:** requested for the server you enter in settings. Firefox host match patterns cover the host rather than a single port; the extension still directs requests to the exact configured origin.

The extension declares optional HTTP(S) host patterns so users can enter their own server. This is not a blanket grant at installation. It does not request access to every visited site. Private browsing is disabled, and capture also rejects private tabs and browser/extension pages.

## Transport and server retention

Use HTTPS/WSS for encrypted transport. A clearly labeled local-development setting permits HTTP only for localhost/private-IP servers. That exception is unencrypted, including login credentials and page content. The extension does not bypass invalid TLS certificates.

After upload, content follows your Jarvis server's normal processing and retention rules. In the current Web implementation, uploaded screenshots are written to disk, page text is stored as a Web text attachment, image processing can copy screenshots into Stash and record memory references, and chat saves conversations and answers. Tools, logs, and configured model providers can retain additional records according to their own configuration and policies. A user-owned server can still send data onward to cloud model or tool providers; selecting local mode is not an extension-level guarantee that every enabled tool is local.

There is no server-side ephemeral/private-chat mode in this extension. Removing an unsent preview prevents its upload. Removing a sent preview, clearing local extension state, logging out, or uninstalling does not remove content already held by Jarvis or its providers. Use the server's conversation, Stash, memory, and retention controls for those records; consult the server operator when you do not control that deployment.

## Controls and contact

You choose the server, when to capture, what to stage, and when to send. **Stop** requests cancellation of current work; completed tool actions and existing saved records are not undone. Reconnection looks up existing requests and never automatically resends uncertain work.

Change or revoke server access in Firefox's extension permissions. Report extension privacy issues through the [Jarvis Voice repository](https://github.com/bigsk1/jarvis-voice/issues). For data held by a configured server or provider, contact that server's operator or provider.
