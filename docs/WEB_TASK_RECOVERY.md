# Web task recovery

Start a task in Jarvis Web, reload the page or leave the conversation, and return
to its saved messages and current task state. A disconnected browser does not
cancel the task. Reopening the conversation restores **Stop** while work is
running; results received while away appear in history without replaying speech.

This guide covers ordinary Web chat turns and Completion Guard repairs. Durable
tool jobs that release the chat use the separate
[background-task lifecycle](BACKGROUND-TASKS.md).

## Behavior

| State | What it means |
| --- | --- |
| Running | This Web server still owns the task. The conversation remains busy. |
| Stopping | Stop was requested. Wait for the worker to settle before sending another turn. |
| Completed | The task returned successfully. Its answer is restored from history. |
| Failed | Processing or persistence failed. The saved turn includes the outcome when storage is available. |
| Cancelled | The worker acknowledged cancellation. Existing completed actions remain completed. |
| Interrupted | No worker owns the unfinished record, usually after a server restart. Work is **not retried**. |

The sidebar labels running, stopping, and interrupted conversations. Listing,
opening, and retention cleanup reconcile unfinished records against an execution
lock. A server crash releases that lock, so stale Running records no longer need
to be opened individually, even if their index entry never recorded admission.
Listing checks document changes and probes active leases; unchanged idle documents
are not parsed again. A saved answer needs an explicit terminal outcome to recover
success or failure; missing metadata means Interrupted. Retention protects live tasks; its dry run projects abandoned tasks
without changing conversation or index JSON.

Connected Web clients subscribe to `conversations:changed` invalidations over the
existing authenticated socket. Successful index writes notify subscribers after
the store locks are released; the client coalesces bursts and serializes list
fetches. Subscribing again after reconnect also triggers a refresh. This updates
only the sidebar, including chats started by Firefox or another device, and never
broadcasts the initiating client's `conversation:created` navigation event.
Active-task refreshes and lease checks continue independently of these events.

A **socket reconnect** preserves the displayed transcript, expanded tool cards,
feedback, reaction controls, draft, and ongoing attachment preparation. It adds
missed messages and reconciles task state. **F5** rebuilds from saved history and
reopens that tab's last conversation, including when idle. Explicit conversation
navigation also rebuilds history and retains its existing attachment-cancellation
behavior. An external Clear, including Clear followed by new messages, is reflected
on reconnect without aborting uploads. Duplicate receipts and overlap rejection
also reconcile in place; rejected optimistic bubbles are removed.

- The active conversation is remembered per browser tab. If the first acceptance
  message was lost, the browser looks up its request ID without resending work.
- One chat or Completion Guard repair can execute per conversation. An overlapping
  send is rejected, and its draft, sources, and tool hints return to the composer.
- Independent conversations can execute in the same mode. Starting work in the
  other mode is rejected until current work finishes or stops: the existing MCP
  tool registry is shared and changing its mode closes its clients. Socket and
  HTTP mode changes and settings reset follow this boundary before changing defaults. The browser
  applies mode changes on acknowledgement; the selector is disabled while the
  displayed task runs. Settings managers themselves are request-local, and task
  configuration and Completion Guard overrides remain scoped to the task's mode.
- Clear and Delete reject active conversations with an explanation. Stop and wait
  first. After a restart, abandoned runs are reconciled on listing or cleanup too.
- Manual Completion Guard controls survive reconnection within their existing TTL
  and the current server lifetime. The server retains up to 50 recent review
  records; these review contexts do not survive a server restart.
- Thumbs up/down can return for the latest eligible response while its review
  context remains available. Completed reactions retain their original experience
  and mode. Feedback stays background work; a new turn can start while it writes.
  The latest feedback event for up to 100 conversations is cached for recovery.
  Lost background feedback context is shown as unavailable, never automatically
  retried. These caches do not survive a server restart.
- Completion Guard repair admission saves its repairing status before launching
  the worker. Stop and overlap protection remain active through follow-up ticket
  writing. Auto-evaluation still runs after the original answer; if a newer task
  wins admission, the proposed repair is superseded.
- While the sidebar contains active tasks, connected browsers refresh it every
  30 seconds, including after leaving an active conversation's socket room.

Stop remains cooperative. A provider call or tool may need to reach its existing
cancellation check or deadline before the task finishes. Offline browsers cannot
submit Stop. Interruption never rolls back external actions; check their results
before asking Jarvis to perform them again.

## Design and compatibility

The execution owner is a conversation and request ID, independent of a Socket.IO
session. Admission saves the user turn and run record together before launching
the worker. Duplicate request IDs in retained history return the saved state
without launching another worker. New first-send IDs map directly to conversation
documents, so creation and retries do not parse the archive. Explicit resume can
also recover older receipts by searching documents; unrelated invalid or corrupt
files are skipped and logged. Listing repairs missing index entries.
A partial admission reports that the worker did not start. This is request deduplication, not a guarantee
that external actions happen exactly once.

[chat_runs.py](../jarvis-web/server/services/chat_runs.py) orders admission,
snapshot delivery, cancellation, and terminal events per conversation. A short
process mutex reserves mode transitions and protects active-owner bookkeeping;
disk writes, config reloads, MCP teardown, and event delivery run outside it.
New admissions are rejected while a settings transition is in progress. JSON
writes still serialize through the store lock, but another conversation's progress
events and cancellation signal do not wait for that I/O.

Status text and feedback caches are bounded. Unsaved outcomes retain their execution
leases and stay in memory until the exact outcome is persisted or the process exits.
An open/reconnect retries persistence, never execution. A storage outage therefore
keeps that conversation protected from retention and further admission; storage-only
readers may still show Running until the outcome is saved.
[conversation_store.py](../jarvis-web/server/services/conversation_store.py) uses
the existing `filelock` dependency to serialize JSON updates across store
instances and replaces each document atomically. Each active conversation also
holds a `.run-<conversation-id>.lock` execution lease across the socket and worker
threads. The OS releases it on process death; empty lock files are retained to
avoid inode replacement races. Conversation and index writes
are separate; outcome reconciliation repairs index fields after a partial write.
A corrupt index produces an explicit error instead of being silently replaced.

[The socket handler](../jarvis-web/server/sockets/chat.py) integrates normal chat,
attachments, workflows, and Completion Guard repairs with the same admission and
Stop path. Browser changes in
[socket.js](../jarvis-web/client/js/socket.js),
[app.js](../jarvis-web/client/js/app.js), and
[chat.js](../jarvis-web/client/js/chat.js) scope events to the displayed
conversation and reconcile full history before accepting later live events.

Run ownership is stored as additive metadata in conversation JSON:
`conversation.run`, user `data._request_id` / `data._run`, assistant
`data._run_status`, and parent-answer `data._repair_run`. Import preserves message
metadata but marks imported active runs and repairing prompts Interrupted; it
never restores an executable run. This recovery path uses conversation JSON and
file locks rather than the background-tool queue database. Older code can read
the chats but does not enforce task ownership; avoid downgrading during active
work.

This supports the existing **single Web server process**, hosted natively or in
Docker, with cloud and local execution. It does not coordinate multiple Web
workers sharing one conversation directory. Native microphone/wake-word behavior,
scheduled jobs, and CLI execution retain their existing ownership models. Live
tool-card history is not journaled: socket reconnect preserves cards already in
the DOM, but cannot recreate intermediate events it never received. F5 restores
the latest status and saved answer data. Browser session storage is optional; when disabled, open the
conversation from the sidebar.

## Contributor checks

From the repository root, run the maintained full core suite for cross-component
regressions:

```bash
./bin/test-suite
```

For a focused recovery check:

```bash
.venv/bin/python -m pytest tests/test_web_task_recovery.py tests/test_web_task_recovery_ui.py tests/test_web_socket_reconnect.py tests/test_conversation_store.py -q
```

The tests use disposable configuration, conversation files, and logs, with
scripted providers. They cover reconnect, duplicate requests, concurrent stores,
execution-lock release, interrupted-run reconciliation, persistence failures,
and browser state methods in Node. They do not establish real provider
cancellation timing or rendering on physical devices. See [Testing](TESTING.md)
for environment setup, isolation, and the separate Firefox extension suite.

For a manual browser check, use a disposable Web instance with temporary data,
configuration, and logs. Start harmless work that takes a few seconds:

1. Reload while it runs. Confirm history, status, and Stop return.
2. Disconnect only the socket during attachment preparation or tool execution.
   Confirm existing cards and drafts survive, and missed answers arrive once
   without replaying speech.
3. Switch conversations, return, and press Stop. Confirm Send stays disabled
   while Stopping, and Clear/Delete explain why they are blocked.
4. Open the conversation in another tab. Check overlap rejection and draft
   restoration. Check that other-mode work is rejected until the active task ends.
5. Stop and restart only the disposable server during work. Refresh the sidebar
   and confirm the conversation is interrupted without resubmitting work.
