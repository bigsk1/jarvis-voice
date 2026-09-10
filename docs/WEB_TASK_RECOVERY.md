# Web task recovery

Start a task in Jarvis Web, reload the page or leave the conversation, and return
to its saved messages and current task state. A disconnected browser does not
cancel the task. Reopening the conversation restores **Stop** while work is
running; results received while away appear in history without replaying speech.

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

Existing conversation JSON remains readable. New metadata is additive:
`conversation.run`, user `data._request_id` / `data._run`, assistant
`data._run_status`, and parent-answer `data._repair_run`. Import preserves message
metadata but marks imported active runs and repairing prompts Interrupted; it
never restores an executable run. There are no new settings,
dependencies, provider protocols, or database migrations. Older code can read the
chats but does not enforce task ownership; avoid downgrading during active work.

This supports the existing **single Web server process**, hosted natively or in
Docker, with cloud and local execution. It does not coordinate multiple Web
workers sharing one conversation directory. Native microphone/wake-word behavior,
scheduled jobs, and CLI execution retain their existing ownership models. Live
tool-card history is not journaled: socket reconnect preserves cards already in
the DOM, but cannot recreate intermediate events it never received. F5 restores
the latest status and saved answer data. Browser session storage is optional; when disabled, open the
conversation from the sidebar.

## Why this improvement

The verified gap affected every long Web task: threads already survived browser
disconnects, but reconnect only rejoined a room, missed final events were lost to
the UI, reload discarded the active Stop target, and Stop acknowledgement unlocked
the composer before execution actually ended. Concurrent JSON updates could also
overwrite each other. Fixing this makes existing assistant capabilities usable
across browser interruptions, without introducing a second job system.

The strongest alternatives were broader source intake, generic tool-result
hydration, and voice continuation. Mixed-source intake and durable source references
already existed at the starting revision; tool-result hydration had a narrower
gap alongside existing previews; voice already had automatic context and required
hardware validation for interaction changes. Task recovery offered the broadest
demonstrated reliability benefit with a contained Web/storage boundary.

## Verification

Run each group in a fresh process from the repository root:

```bash
timeout 120 .venv/bin/python tests/run_web_recovery_checks.py core
timeout 120 .venv/bin/python tests/run_web_recovery_checks.py guard
timeout 120 .venv/bin/python tests/run_web_recovery_checks.py adjacent
timeout 120 .venv/bin/python tests/run_web_recovery_checks.py settings
timeout 120 .venv/bin/python tests/run_web_recovery_checks.py executors
timeout 90 .venv/bin/python -m pytest -q tests/test_docs_integrity.py
```

Implementation verification results (2026-09-09): core **173 passed**; guard
**19 passed and 7 subtests passed**; adjacent **32 passed**; executors **93 passed**;
settings **44 passed**; documentation **4 passed**. The executor group passed in
the initial implementation; its unchanged paths were not rerun for the review
follow-up. Before implementation, the reconnect, mixed-attachment
chat, conversation-title, and workflow-roundtrip group passed all **35** tests.

The full monolithic suite subsequently passed **3,390 tests and 145 subtests**
in **121.22 seconds**, with no skips. It ran as `.venv/bin/python -m pytest tests -q`
inside a disposable Bubblewrap checkout using the same repository environment;
host data, credentials, audio devices, and external networking were inaccessible.
Four test files now supply temporary local config, mock the embedding preflight,
and check shipped profile templates instead of operator-installed copies.
For comparison, unmodified pre-feature `a924250` reproduced the exact same five
failures under identical isolation (**3,295 passed, 5 failed, 145 subtests passed**);
the feature before those fixture corrections had **3,381 passed, 5 failed, 145
subtests passed**. Those five failures came from existing environment assumptions.

Syntax and scoped lint checks:

```bash
node --check jarvis-web/client/js/app.js
node --check jarvis-web/client/js/chat.js
node --check jarvis-web/client/js/socket.js
.venv/bin/ruff check jarvis-web/server/services/chat_runs.py jarvis-web/server/services/conversation_store.py tests/test_web_task_recovery.py tests/test_web_task_recovery_ui.py tests/run_web_recovery_checks.py
.venv/bin/ruff check --select E9,F63,F7,F82 jarvis-web/server/app.py jarvis-web/server/sockets/chat.py jarvis-web/server/routes/api.py jarvis-web/server/services/chat_runs.py jarvis-web/server/services/conversation_store.py
git diff --check
```

These checks pass. Full Ruff output for the existing large socket/API modules was
also compared with the starting revision: 30 and 40 existing diagnostics
respectively, with no new diagnostic counts by code and message (ignoring moved
line references). Those preexisting lint issues were left outside this change.

The [runner](../tests/run_web_recovery_checks.py) uses disposable configuration,
stash paths, conversation files, and logs, and blocks Python network connections.
The core group includes real Flask-SocketIO in-memory clients and a bounded real
worker thread with a fake provider, concurrent store instances, storage fault
injection, a real child-process lock-release check, restart reconciliation, and production browser methods in a
Node VM. Fault tests include missing index admission/orphan rows, unrelated corrupt
documents, uncertain assistant outcomes, unsaved failures surviving sidebar and
retention reads, slow fsync and mode reload alongside other tasks, and repair
admission/announcement/launch/execution failure/ticketing. The other groups cover Completion Guard, usage metadata, mode scoping,
chat-only policy, PDF/vision failures, cancellation, and pipelines.

Startup tests also exercise the vendored Socket.IO client's event buffer. Its
session-ready event can arrive before the public connect callback; the wrapper
must already accept history-load and receipt-resume requests at that point. These
cases reproduce the hard-refresh bug where a selected chat stayed blank until
clicked again, and verify both handshake orders without opening a network connection.

Keep these groups separate: the existing Completion Guard test module installs
global Flask stubs that conflict with other modules during combined collection.
No paid APIs, live databases, host audio devices, listening servers, or production
service restarts are needed. Browser rendering on actual devices and real provider
cancellation timing remain manual checks.

For manual review, use a disposable Web instance with temporary data/config/log
paths and a local model already available there. Start a harmless task that takes
a few seconds:

1. Reload while it runs. Confirm history, status, and Stop return.
2. Disconnect only the socket during PDF/audio/image preparation, during tools,
   and while feedback, Guard, and thumbs are visible. Confirm preparation and
   existing cards survive; missed answers and feedback arrive once, without speech.
3. Start again, switch conversations, return, and press Stop. Confirm Send stays
   disabled while Stopping, and Clear/Delete explain why they are blocked.
4. Open that conversation in another tab. Check overlap rejection and draft
   restoration; check that other-mode work is rejected until the active task ends.
5. In the disposable instance only, stop its server during work and restart it.
   Refresh the sidebar: it should show interruption without opening the thread.
   Open it and verify no work is resent. Retention dry runs should include an old,
   unpinned abandoned thread while preserving a live task.
