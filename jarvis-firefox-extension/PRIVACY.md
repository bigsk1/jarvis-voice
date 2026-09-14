# Jarvis Companion privacy information

Jarvis Companion is a client for the Jarvis Web server you configure. The extension does not operate its own cloud service, include analytics, or send telemetry to its author.

## What is transmitted

When you connect, the extension checks server status and capabilities. Signing in sends your Jarvis Web password to that server's login endpoint. Subsequent authenticated REST requests use a Bearer token; Socket.IO supplies the token in its authentication handshake, not in a URL.

When you choose **Send** or **Analyze screenshot**, the extension can transmit:

- The message you composed or the displayed action's default question.
- The staged screenshot, resized to JPEG with a maximum edge of 1,024 pixels at quality 0.85.
- The selected text or link you explicitly staged.
- Source page titles, URLs, and screenshot capture time included with that content.
- Conversation/request identifiers and the selected Jarvis cloud/local mode.

Connection recovery and opening history can retrieve saved conversations without another Send action. Normal HTTP/socket communication also exposes network information such as your address to the server. The extension does not continuously capture tabs, read browsing history, inject page scripts, or upload a screenshot merely because its preview is visible.

Firefox's declared data categories are `authenticationInfo`, `personalCommunications`, `websiteContent`, and `browsingActivity`. Transmission to a user-owned Jarvis server is still transmission. The extension does not declare or implement optional analytics collection.

## What stays in Firefox

| Storage | Contents | Lifetime |
| --- | --- | --- |
| `storage.local` | Server URL and connection preferences | Until changed or extension data is removed. |
| `storage.session` | Login token, bounded chat/recovery state, source metadata, and unsent draft/attachment | In memory during the extension session; cleared when Firefox exits or the extension is disabled/reloaded. |

The extension does not persist your password, put credentials in page scripts or URLs, use synchronized extension storage, or save the token in `storage.local`. An open sidebar or pop-out exchanges a small local ping/pong with the background every ten seconds; it contains no page data or credentials and is not transmitted to the server. Closing the view stops its timer. Session storage is not an encrypted credential vault. Password-manager behavior and operating-system memory handling are controlled by Firefox and your system.

Closing the pop-out does not erase the session or cancel an accepted Jarvis request. Logging out removes the extension's token; the current Jarvis server token model does not individually revoke that token. Sign in again to recover previously accepted work.

## Permissions

- **`activeTab`:** temporary access after a toolbar or context-menu action, used for the selected webpage and visible capture.
- **`menus`:** Jarvis actions for page capture, selected text, and links.
- **`storage`:** settings and session recovery.
- **Optional host access:** requested for the server you enter in settings. Firefox host match patterns cover the host rather than a single port; the extension still directs requests to the exact configured origin.

The extension declares optional HTTP(S) host patterns so users can enter their own server. This is not a blanket grant at installation. It does not request access to every visited site. Private browsing is disabled, and capture also rejects private tabs and browser/extension pages.

## Transport and server retention

Use HTTPS/WSS for encrypted transport. A clearly labeled local-development setting permits HTTP only for localhost/private-IP servers. That exception is unencrypted, including login credentials and page content. The extension does not bypass invalid TLS certificates.

After upload, content follows your Jarvis server's normal processing and retention rules. In the current Web implementation, uploaded screenshots are written to disk, image processing can copy them into Stash and record memory references, and chat saves conversations and answers. Tools, logs, and configured model providers can retain additional records according to their own configuration and policies. A user-owned server can still send data onward to cloud model or tool providers; selecting local mode is not an extension-level guarantee that every enabled tool is local.

There is no server-side ephemeral/private-chat mode in this extension. Removing an unsent preview prevents its upload. Removing a sent preview, clearing local extension state, logging out, or uninstalling does not remove content already held by Jarvis or its providers. Use the server's conversation, Stash, memory, and retention controls for those records; consult the server operator when you do not control that deployment.

## Controls and contact

You choose the server, when to capture, what to stage, and when to send. **Stop** requests cancellation of current work; completed tool actions and existing saved records are not undone. Reconnection looks up existing requests and never automatically resends uncertain work.

Change or revoke server access in Firefox's extension permissions. Report extension privacy issues through the [Jarvis Voice repository](https://github.com/bigsk1/jarvis-voice/issues). For data held by a configured server or provider, contact that server's operator or provider.
