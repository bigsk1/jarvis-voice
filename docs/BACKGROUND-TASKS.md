# Background tasks

Web chat can accept a reviewed long-running tool as a background job. Jarvis saves a receipt, frees the chat so you can send another message or call another tool, then updates the original card and adds an answer in the same conversation when the work finishes. The operator chooses which tools may do this in **Settings → Tools → Background tasks**.

## How background work finishes

Every background tool uses the same admission, saved job, card, late-answer, allowlist, and recovery machinery. Its adapter answers one question: **who observes the work until there is a result?**

| Adapter | Who observes completion? | Current examples |
| --- | --- | --- |
| `local_skill_v1` | The task worker starts a reviewed local skill and supervises its process group until it exits. | `convert_file` |
| `remote_skill_v1` | The worker runs the same kind of skill, but that skill calls an external API and waits or polls for a result. The worker is still the observer; stopping its process does not prove the provider stopped. | `generate_image`, `generate_video`, `generate_music`, `create_social_clip`, [Browser Use Cloud](BROWSER-USE-CLOUD.md), [Craft editing tools](../jarvis-craft-tools/README.md), [Docling](tools/docling-tool/README.md) |
| `apify_actor_v1` | The worker submits one ordinary Actor, durably saves its native run ID, and polls that same run. A replacement worker can resume observation without submitting again. | Optional [Apify Actors](mcp/APIFY.md) |
| `http_callback_v1` | The worker submits once and stops waiting. A separate service keeps the job identity and later POSTs an authenticated progress or final event to Jarvis. | Local Browser Use; optionally, an owner-installed remote agent over HTTPS |

These adapters share the same chat system and differ in who owns completion. A compatible local or remote skill needs reviewed manifest settings and a trusted binding to the shared runner. A callback tool also needs a real submit/receipt service, a configured source and credential, and a reviewed binding; adding a manifest flag or a URL alone cannot make a tool runnable. [Task callbacks](TASK-CALLBACKS.md) documents that protocol.

Optional [Prompt Guard screening](PROMPT_GUARD.md) reviews selected final results
at worker or authenticated callback completion, using the originating job's mode.
Both Browser Use tools are included in the default selection. Confirmed hits
withhold returned text and deliver a neutral incident notice without rerunning
the tool. Known completion settles normally with a failed result presentation;
uncertain remote work stays `needs_attention`. Scanner outages continue normally.
This screens returned reports; browser agents' internal observations are separate.

Progress is separate from completion. The callback protocol accepts `task.progress`, but a service must actually send it; the expanded Web task card shows the latest short phase, not a full activity stream. Browser Use sends phase updates, while a service that only sends a final callback will appear idle until it finishes. OpenCode uses a foreground tool card with richer live status and has no background binding.

**Both Browser Use tools are Web-only and background-only.** Local `browser_use` requires the saved allowlist, worker and callback service. Hosted `browser_use_cloud` requires the saved allowlist, worker and a Browser Use Cloud API key; its V4 observer polls in the worker, so Jarvis's incoming callback receiver is not needed. Unmet requirements hide either tool from model selection; stale or forced calls fail without starting browser work. Voice, Talk, Firefox Companion, query API, CLI and workflows cannot run either tool; there is no foreground fallback.

For tools declaring `execution.background.required`, runtime discovery adds unmet background/callback requirements to the existing request block list. The tool can remain enabled and indexed while hidden from Tool RAG selection, exact tool lookup and model schemas. Callback tools require an enabled receiver and trusted source with a successful setup test, usable credentials/key storage, and success/failure events. These read-only checks never edit the saved manual block list or create jobs. Web computes readiness once per turn and shares it across routing and Tool RAG; selected tools hidden by AdmissionDenied log the reason. Admission rechecks live policy before queueing; the worker checks again before submission. Ordinary conversion/media tools retain their existing foreground availability. This does not require a Tool RAG resync when toggling settings.

**Background admission and incoming webhooks default off; the saved tool list starts empty.** Execution requires a running Linux worker and saved Web preferences. The native start-all and UI groups start that worker; admission remains opt-in. Importing the package creates no storage or service. Missing workers affect background readiness only. An enabled background call reports unavailability rather than silently running foreground; unrelated chat and foreground tools keep working.

Local conversion needs no Tailscale network, VPS, or public endpoint. [Task callbacks](TASK-CALLBACKS.md) provide an optional authenticated inbox and **Settings → Integrations** controls. The opt-in [Browser Use](BROWSER-USE.md) tool uses that inbox; private callback integrations can be installed separately and are absent from public clones. The short foreground `openclaw` tool, standalone relay, and `/api/alerts` are separate systems. Firefox clients can view task updates but cannot admit background work.

## Conversation context

Each subsequent chat turn receives a bounded task-store snapshot for its conversation generation across both modes, including after new admissions are disabled. Each job retains its original execution mode; switching chat mode does not hide its status or change execution/delivery authorization. Evidence includes the last reported progress, update time, and attention reason when available. Execution state and answer-delivery state stay separate: a finished tool can still have a pending follow-up answer. Current facts supersede old receipt prose; unrelated replies should not recap jobs. Foreground context and late answers share explicitly labeled input arguments and returned results, so a newly created output artifact is not mistaken for a mismatched input solely because its stash identifiers differ.

The eight-job snapshot prioritizes unfinished/uncertain work, then pending answer delivery, then recent terminal outcomes. Cancelled and expired jobs have terminal rank; they do not displace newer successes as unfinished work. Expiry means a job missed its admission deadline without dispatch; result archival is a separate retention flag.

## Admission and execution

Tool manifests may declare capability outside the provider's parameter schema:

```json
{"execution": {"background": {"supported": true, "adapter": "reviewed_adapter_name"}}}
```

This metadata grants no execution authority. A matching trusted adapter binding, healthy worker, enabled admission, and server-created Web authorization are required. Unknown metadata or unavailable workers disable background admission without hiding an otherwise available foreground tool. `execution.background.required: true` additionally forbids foreground execution; Browser Use declares this requirement. There is no model-controlled `execution_mode` parameter or inherited background context for nested workflow steps.

The server snapshots the saved tool list for each authenticated Web text request. Background-only tools get a read-only eligibility check before model selection. An actual selected call validates current capability, policy and blocks again. Authorization and the held job are saved atomically; unrelated turns create no authorization rows. Authorization records the conversation generation, source request, mode, allowed tool, policy fingerprints, and original provider/model. It does not copy user text: late answers read the original request from the conversation. The admission transaction rechecks both the master switch and tool membership, so unchecking a tool prevents new jobs even if routing already began. Client-supplied `background_tools` cannot grant or override permission. The executor receives the context explicitly for top-level Web invocations. Talk, Firefox Companion, voice/CLI, query API, schedules, and workflow steps keep ordinary foreground tools, reject background-only tools, and reject leaked background receipts instead of treating them as completed work.

When a Web turn has an eligible background-tool selection, the router adds the receipt policy to that request's effective system instructions. It explains admission versus completion and Jarvis queue IDs versus provider task IDs before the model chooses a tool. The stable policy precedes the existing composed prompt, keeping it and the baseline instructions ahead of changing clock/context text. Enabled and disabled background settings produce different prefixes; ordinary turns with the same setting retain the stable prefix. This is one conditional runtime addition shared by V1–V4; it requires no edits to baseline prompt files or model overrides. Native provider continuations inherit the initial system message. Current job snapshots remain separate context evidence, and Memory conversation records save the original human request rather than the augmented routing input.

Saved background preferences do not override effective manifest/profile enablement, required ENV/config availability, or Web tool blocks. Settings keeps unavailable rows visible with an explanation and disables new selections; a saved choice from another mode remains visible and can be unchecked. The status request checks its selected mode, and the worker rechecks current policy before launching accepted work. Apply ordinary configuration/profile reload or restart steps after editing configuration files; a cached discovery list is not an execution grant. Disabling new background admission alone still lets accepted work drain. Blocking a tool does not cancel work already running at its provider.

The persistence sequence is:

1. `TaskStore.admit()` writes `queued` + `held` and returns a typed receipt before any foreground `Popen` or subprocess wait.
2. Web saves its acceptance answer/card and `pending_jobs`.
3. `ChatRuns.finish()` persists the source outcome and releases the conversation lease.
4. Web derives `ReceiptEvidence` from the saved source request and matching answer, then releases the held job. Recovery uses source history even if a later run is current.
5. A worker claims the job with an owner, attempt ID, fencing token, and lease.
6. The terminal result and pending outbox record commit in one SQLite transaction.

Identical invocation identities reuse one admission; different work under that identity conflicts. Distinct invocation IDs remain distinct even with identical arguments. A pending receipt is excluded from successful tool accounting, Completion Guard/repair, feedback, and outcome learning.

Within one Web message, the existing exact-duplicate guard treats an accepted tool call as already seen and blocks the same tool/arguments before another admission. Changed conversion arguments remain separate jobs, and a new user message may repeat work. The existing single-attempt caps for expensive generators still apply, including when arguments differ. There is no composer override for either guard. Duplicate tracking does not count receipts as successful execution or change durable invocation identity.

An admission's `job_id` identifies Jarvis's queue, not a provider task. If the
model tries to pass a current turn's admitted job ID as a remote tool's
`task_id`, `job_id` or `run_id`, the shared executor returns the existing
admission receipt. It does not poll the provider or queue another job. This
keeps the source turn able to settle and release its accepted work rather than
ending with a misleading collection failure. Native provider IDs continue
through normal tool execution. Independent tools remain available; admission
does not end the whole routing turn. Failed, cancelled or interrupted source
turns still cannot release held jobs.

A matching slash-workflow command takes precedence and runs its ordinary foreground pipeline. Saved background preferences are not inherited by workflow steps. The unsupported-caller guard also recognizes `status=accepted` plus `job_id` as a leaked receipt; it deliberately accepts that broader signal as well as the typed `background_admission` marker.

Adapters receive `ExecutionContext`, use its mode environment for children, and check ownership/deadline/shutdown during cooperative work. A returned result means completion is known; `KnownFailure` means known unsuccessful completion. Unexpected errors and interruption without termination proof produce `needs_attention` without automatic execution retry. A surviving local supervisor can report verified process-group termination for its exact attempt after shutdown or lease/deadline expiry. That settles as failed (or cancelled if cancellation was requested) and releases capacity. This report cannot overwrite an operator disposition or cross a conversation-disposal fence. Remote work remains uncertain after stopping its local observer.

The reviewed Apify adapter separates submission from observation. Its immutable
native checkpoint lets another worker acquire a new attempt and fence for the
same running slot, mode and deadline. Recovery calls only the observer; it never
repeats submission. This does not change `remote_skill_v1` or its media tools.
Missing native handles, expired deadlines, and disposed conversations remain
ineligible for observation recovery. See [Apify recovery and limits](mcp/APIFY.md).

Tool timeouts and uncertain outcomes also queue a durable notice in the same
conversation. A remote observer reaching its waiting limit does not prove the
provider failed or stopped. The notice says what Jarvis can confirm and that no
automatic retry was started; it remains visible after reconnect or reload.
Timeout/uncertainty notices do not depend on an LLM summary call. They use the
existing delivery outbox, source settlement and conversation-generation fences.
Older uncertain jobs without a notice receive one when the store next reconciles,
unless their conversation
was cleared or deleted.

When a skill returns unconfirmed results, the worker preserves its bounded
result and native task/receipt references for the timeout notice and the next
turn's background context, even when expiry recovery wins the race. Only the
same expired attempt can enrich this evidence; it cannot restore its lease,
release its capacity, overwrite an operator decision or cross conversation
disposal. New recovery details invalidate a pending notice; if the notice has
already been delivered, one additional notice carries those details. Suppressed
deliveries stay suppressed. Identical evidence does not queue another notice.

Remote skills can emit the existing tool-progress protocol with a `recovery`
object as soon as submission returns, before waiting for completion. Recognized
fields are `task_id`, `job_id`, `request_id`, `run_id` and `receipt_stash_ref`;
identifiers and Stash references are bounded and validated. Later progress
retains these fields, and expiry recovery includes them without requiring final
child stdout. If the provider never returns an identifier, Jarvis cannot invent
one or infer completion from files that happen to exist in Stash.

Ask “What is happening with the existing task?” or “Check that conversion;
do not upload it again.” These questions do not authorize another submission.
Jarvis can check or collect existing provider work when that tool supports it
and a usable task ID was returned. No new execution is scheduled just because
a notice was delivered. A notice is not a completion result; remote work after
the waiting limit does not automatically receive another observer.

**A `needs_attention` job with an `attempt_id` still reserves a running slot.** Clearing a conversation or stopping a worker is not proof that the operation stopped. The task inspector requires an explicit stopped-operation attestation, evidence, and failed/cancelled disposition before releasing this capacity. The evidence and state change commit together; reconciliation never replays execution.

## Delivery and recovery

The Web coordinator drains on startup and every second. One process owns its lock for a task database. It observes active attempts, pages other job updates, recovers held receipts, and attempts pending deliveries. SQLite write transactions never span model generation; final projection holds a short fence transaction through atomic conversation JSON replacement.

If another Web process owns that lock, startup continues with foreground chat available. The losing process reports coordinator unavailability and refuses background admission or enabling; it can still disable new admission. It does not start a second drain loop. A later start/status request can acquire ownership once the previous coordinator releases the lock.

Task-store corruption, incompatible schema, or inaccessible storage must not hide conversation JSON or abort ordinary chat. Conversation reads log an unavailable fence lookup and skip task-fence recovery until storage is repaired. Admission, delivery, disposal, and import protections still fail closed. If preferences cannot be read, calls to reviewed background-capable tools return an availability error rather than silently launching inline; unrelated chat/tools remain usable. Coordinator initialization failure also leaves Web serving chat.

After a delivery transaction commits or defers, Web republishes the source card with the current outbox revision. A late answer therefore clears “reply pending” without another user message or reliance on the timestamp paging cursor. Restart recovery still restores cards and the saved continuation.

Normal chat status questions receive the current delivery state separately from the tool's execution state. Late-answer generation omits that internal delivery state: the answer being composed is itself the result delivery message, so it must not describe its own result as still awaiting delivery. This does not mark delivery complete early; the outbox changes to `delivered` only when projection commits.

Authorization records retain execution metadata without a copy of the user query. Clear/delete removes authorizations for the disposed generation. Result retention also removes old orphan authorizations and authorizations whose referencing results have all been archived; active work and pending follow-ups keep the metadata they need. Restart Web and worker together after an upgrade that changes the task schema.

A continuation has its own delivery lease (30 seconds, renewed every five), stable ID, parent job/request, and `kind=continuation`. It snapshots idle conversation history under the mode gate, then generates with the original provider/model and all tools disabled **without holding the chat lease**. New foreground messages can run while generation is in progress. It takes the conversation lease only for the brief append/settlement step. It does not invoke the orchestrator or repair loop. At most two deliveries generate concurrently, with one per conversation.

The generated answer is cached in the outbox before JSON projection. Projection retries reuse that output when its saved history fingerprint still matches. If another message changed the history during generation or a delivery retry, the coordinator discards only the generated prose and summarizes again after foreground chat settles. Already projected continuation IDs recover without regeneration. A saved continuation ID prevents duplicate messages when JSON replacement succeeds but the outbox commit fails. Model failures defer delivery with bounded backoff; the completed tool result remains accessible with a “reply delayed” status. A process death during generation may repeat the summary call after expiry, but never authorizes another tool execution.

`task:updated` revises the original card; `chat:continuation` appends the late answer. They use a separate authenticated `tasks:<conversation>` subscription and never emit legacy `tool:*` or `chat:response` events. Revision and generation checks reject stale events. Web and Firefox preserve foreground progress, Stop state, drafts, attachments, and Talk audio. Saved conversation history restores missed events.

Live and restored Web continuations use a separate DOM renderer. Markdown formatting remains readable; raw HTML is literal text, and links accept HTTP(S) or fully parsed, encoded stash references. Successful tool results with saved media show inline image previews (with the existing lightbox), video controls, or audio controls, plus Open/Download actions. The shared media renderer uses the existing media styles and builds DOM nodes from structured results; it never feeds late data into legacy HTML widgets or rich-content hydration. Media loads only from encoded same-origin stash URLs, with no autoplay or provider URL fallback. Unsupported files retain viewer links, and failed previews keep their file actions.

New continuations persist their job's execution mode for stash URLs. Older saved replies recover it from the source receipt card without rewriting conversation history, so a later chat-mode switch does not select the wrong stash. Each continuation has response-only Copy; it preserves the current foreground action rail. Trailing continuations do not change that answer's reaction eligibility, while a later user message still invalidates it.

Ordinary clear/delete refuses outstanding work. Explicit disposition fences the generation and suppresses pending delivery before clearing/deleting JSON. The durable fence completes recovery if the JSON operation fails afterward. Retention preserves outstanding jobs, fails closed on task-store errors, and its dry run makes no changes. Imports cannot overwrite pending destinations or deleted IDs.

## Web controls and authentication

**Settings → Tools → Background tasks** contains the master switch and saved list of tools allowed to run in the background. Changes save immediately and apply to Web text chat and tool dialogs in both modes, across messages, tabs, reloads, and restarts. The composer has no background checkboxes. Preferences can be saved while the worker is offline; readiness is shown separately.

**Browser Use has one normal setup action in this same panel on native installs.** Click **Set up and enable** once. Jarvis checks Docker, downloads the pinned optional image when needed, provisions and verifies its private callback source, enables the receiver and saved tool permission, and starts the managed tmux helper. Setup returns immediately while Settings polls progress; a second click joins the same attempt, and interrupted setup can be retried. Docker deployments show a native-only explanation instead of setup controls. The Integrations tab keeps advanced callback and delivery controls; it is not part of the normal Browser Use setup. Afterward the usual Start All groups manage the helper automatically.

To use conversion in the background, enable the master switch and **Convert file** once. The **Convert File** dialog uploads, submits its known tool arguments, and receives a short durable queue receipt without a model routing or receipt-writing call; a short note shows whether it will run in the current turn, run in the background, or cannot queue because the worker is unavailable. Typed conversion requests follow the same server policy through ordinary model routing. With background execution off, Convert retains its foreground chat path. Explicit submissions use the reviewed local skill manifest and shared runner; the client cannot grant permissions or name an arbitrary script. Turning the master switch off retains the saved tool choices.

**Manage tasks** in Settings or the sidebar thread button opens a centered, responsive task dialog. It shows progress/attention counts, a separate worker setup notice, task cards and artifact links, collapsible conversation/tool/state filters, pagination, and advanced limits/retention. It never navigates away when another conversation completes.

**Unread** means task details have not been viewed; opening **Details** marks them read. It is independent of whether the follow-up was delivered. **Preview retention** checks the saved retention period and displays the next cleanup batch count beside the button, including when zero results qualify. The preview changes nothing. Retention removes old completed task result details after delivery or suppression, while keeping saved messages and generated files.

Disabling admission lets accepted work and pending delivery drain. Stopping the worker is a separate deployment action. Queued cancellation prevents dispatch; running conversion shows **cancel requested** until the process group is verified stopped. Browser Use offers per-job Cancel on its task card and in Manage tasks; its helper acknowledges only after stopping that attempt's container, and saved partial research remains available on the card/Details without a new assistant reply. A completion may win a racing cancel request. Lost ownership or uncertain execution stays **needs attention** with its slot reserved; use Details to record termination evidence. Retry follow-up only regenerates or projects the answer, never reruns the tool. Suppression fences an in-flight answer.

Changing the same conversation's mode affects the next foreground turn. The accepted job and its continuation retain their original mode/provider/model. Reconnection restores both the saved card and late answer.

| Web route | Purpose |
| --- | --- |
| `GET /api/background-tasks?mode=cloud` | Settings, supported tools, worker/coordinator readiness |
| `PATCH /api/background-tasks` | Admission switch, saved `background_tools`, capacity limits, result retention |
| `GET /api/background-jobs?conversation_id=…&tool=…&state=…&offset=0&limit=25` | Paginated job cards and counts |
| `GET /api/background-jobs/<id>` | Arguments, result, attempts and operator evidence |
| `POST /api/background-jobs/<id>/actions` | `cancel`, `read`, `reconcile`, `retry_delivery`, `suppress_delivery` |
| `GET /api/background-tasks/retention` | Read-only preview of the next archival batch |
| `POST /api/background-tasks/conversations/<id>/dispose` | Explicit `clear`/`delete` with the current `generation` |

These routes require configured Web authentication and an explicit valid bearer token. Cookie-only auth, query tokens, and permissive loopback defaults do not grant feature access. Browser operator requests must match the Web origin; automatic background admission additionally requires an actual allowed Origin on the Web socket. When TLS terminates at Tailscale or another reverse proxy, set `JARVIS_WEB_BACKGROUND_ALLOWED_ORIGINS` on the Web process to a comma-separated list of exact external origins (for example, `https://jarvis.example`). Forwarded headers alone never grant origin access. Read-only subscriptions allow authenticated Firefox clients on their extension origin or without Origin; those clients do not inherit saved background execution preferences. Credentials are checked again on task event delivery. Operator routes remain on Web; the optional FastAPI task callback receiver uses separate mandatory source authentication.

## Storage and supervision

The default path is repository-relative `data/background_tasks.db`, independent of the working directory. Callers can provide an absolute path for isolation. One control database serves both modes, outside MemoryDB synchronization. Explicit initialization applies ordered transactional migrations and rejects unknown versions. The database and SQLite companions have owner-only permissions.

Defaults: two globally running local execution slots, two per adapter, five outstanding jobs per conversation generation, and 100 queued jobs. A callback job releases its execution slot once its attempt is durably bound and `callback_waiting=1`; it remains visible as running until a terminal callback or deadline. Unknown `needs_attention` attempts still reserve capacity until reconciliation. Result retention defaults to 30 days (configurable from 1 to 3650). Arguments, progress, and results are bounded. Workers reconcile on startup, poll every second with jitter, and heartbeat every five seconds with a 30-second lease. PID files do not confer execution authority.

Web starts its coordinator only when task storage exists or an authenticated operator explicitly initializes controls. An unstarted admission that reaches its deadline becomes **expired**, without executing. A started attempt whose ownership/deadline expires becomes **needs attention** unless its surviving local supervisor reports verified termination for that attempt, or a reviewed Apify native checkpoint permits observation recovery before the original deadline. Cancellation and expiry are persisted flags over the existing physical state constraint, preserving old task databases without a destructive table rebuild.

Every hour, the coordinator archives at most 100 old terminal result/progress payloads and cached follow-up outputs. Active/uncertain jobs and pending follow-ups are protected. Invocation identities, admission records, attempt history, and operator evidence remain; a repeated identity cannot execute again after archival. Conversation messages and stash artifacts are untouched. Archived payloads cannot be retried. The UI preview makes no writes. This is result-payload retention, not deletion of conversation history or a backup compaction policy.

## Native worker

The task store uses SQLite WAL mode with short-lived connections. `background_tasks.db-wal` and `background_tasks.db-shm` can appear during access and disappear when the last connection closes. The worker and Web drain check frequently, so this can cause IDE Explorer flicker even while idle. SQLite manages these files; they are already ignored by Git. An IDE Explorer exclusion for `**/*.db-wal` and `**/*.db-shm` can hide the visual churn without changing storage behavior.

After updating the checkout, restart Web so it loads the new task routes and adapter binding. Use Linux with the normal Jarvis runtime environment (`JARVIS_VENV`, default `~/jarvis-venv`) and local conversion binaries. Audio/video conversion needs ffmpeg; images need ImageMagick; raster-to-SVG additionally needs Potrace. Missing backends produce a truthful failed result for the requested conversion.

To inspect status or run the worker in a terminal:

```bash
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker status
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker run
```

**Tmux is the standard native service supervisor.** It supports starting, stopping, attaching to, and debugging the application. A systemd user-unit generator is available for an alternative manual deployment; normal startup commands do not install or enable systemd units.

The normal native `bin/start`, `bin/start --ui-only`, and `bin/start --no-api` groups also start **jarvis-task-worker** and an already-configured **jarvis-browser-use** helper in tmux. Existing aliases for those commands need no changes. Browser Use is skipped quietly until its one-time Settings setup has been completed. `bin/start --stop` stops both with the other sessions. One worker serves both cloud and local jobs, including when Web changes modes. Starting a worker never enables admission or adds tools to the saved allowlist.

```bash
./bin/start task-worker
./bin/start --stop-task-worker
./bin/start browser-use
./bin/start --stop-browser-use
./bin/start --list
tmux attach -t jarvis-task-worker
tmux attach -t jarvis-browser-use
```

The dashboard's Services tab includes lifecycle, status, and logs for both the task worker and Browser Use. The start groups and dashboard delegate lifecycle management to each service CLI; `bin/start` only groups them. Browser Use setup and service controls live in Settings → Tools, while Settings → Integrations remains its advanced callback audit surface.

`tmux attach -t jarvis-browser-use` shows live helper/callback messages. Browser
navigation and lifecycle audits are retained separately in owner-only
`logs/browser-use/browser-use-YYYY-MM-DD.jsonl`; see [Browser Use](BROWSER-USE.md)
for its audit fields, privacy boundary, image upgrade procedure, and Grafana-ready
log shape. `bin/cleanup-logs` includes this installation directory under the same
60-day default as other dated logs when the cleanup command is run.

The worker uses the same `JARVIS_VENV` runtime environment as the other native services (default `~/jarvis-venv`); a repo `.venv` is not required. An already healthy worker is reused. A manually launched or systemd-managed worker stays under its original supervisor; stop it there before switching to tmux. Native stop-all manages its own tmux sessions.

When attached to the worker pane, you should see a startup message, **Task worker ready**, and the saved admission status/tool list. A ready worker may be idle with admission disabled; enabling Settings → Tools is not needed to see startup output. Settings changes and job starts, outcomes, and shutdown are logged as events. Idle polling and healthy heartbeats produce no repeated lines. Logs identify the job/tool/mode but omit arguments, result bodies, and arbitrary adapter exception text. “Result saved for Web delivery” means execution has finished; Web still owns the late chat answer.

### Persistent diagnostics

Web and worker also append structured lifecycle records to
`logs/background-tasks/background-tasks-YYYY-MM-DD.jsonl`. Dates and timestamps
use UTC. The existing **Logs** page (`/logs`) automatically discovers this folder
after its first event; search a job ID to follow it across both processes. These
files are separate from the composer's live **Server Logs** source filters.

Records include startup/shutdown, saved settings, admission/rejection, job start
and outcome, recovery counts, operator actions, and continuation delivery/errors.
They carry `level`, `component`, `event`, job/conversation/request identifiers,
tool, adapter, mode, state, and queue/run timing where available. Provider output,
prompts, arguments, credentials, raw exceptions and operator evidence text are
excluded; retained tool diagnostics remain in **Manage tasks → Details**.
Routine polling, healthy heartbeat renewals and per-token progress produce no
records. Repeated infrastructure errors are limited to one matching event per
minute, with a suppressed-repeat count on the next record.

Writes use a short cross-process file lock and owner-only data files. Failure to
write diagnostics leaves admission, execution and delivery working and produces
a console warning. Logs are best-effort diagnostics; SQLite remains the durable
task record. `bin/cleanup-logs` includes this folder under its existing retention
policy (60 days by default), independently of task-result retention. A custom
`--db` writes under `<database-directory>/logs/background-tasks/`, keeping test
and alternate installations out of the main logs.

```bash
# Recent lifecycle events (UTC date)
tail -20 "logs/background-tasks/background-tasks-$(date -u +%F).jsonl" | jq .
# Failures and uncertain outcomes
jq 'select(.level == "ERROR" or .state == "needs_attention" or .state == "failed")' logs/background-tasks/*.jsonl
```

For a future Grafana deployment, a collector can tail
`logs/background-tasks/*.jsonl` and send the records to Loki. Grafana Alloy's
[`loki.source.file`](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/)
supports file collection. Keep job IDs as searchable JSON fields and use stable
labels such as service/component/mode. No collector, endpoint, or external log
upload is enabled by this feature.

### Optional systemd installation

To use automatic restarts independent of tmux, generate and inspect the portable systemd user unit, then install it. Stop any tmux-managed or manually started worker first; run only one supervisor for a task database.

```bash
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker unit > /tmp/jarvis-task-worker.service
cat /tmp/jarvis-task-worker.service
mkdir -p ~/.config/systemd/user
cp /tmp/jarvis-task-worker.service ~/.config/systemd/user/jarvis-task-worker.service
systemctl --user daemon-reload
systemctl --user enable --now jarvis-task-worker.service
```

The generated unit pins this checkout, interpreter and database path. Regenerate it if those move. `--db /absolute/path/tasks.db` is available for isolated runs; production Web and worker must use the same control database. Use the matching deployment environment/profile on both processes. Login-independent user services require the host's usual user-service/linger configuration.

```bash
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker status
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker stop
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker start
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker restart
journalctl --user -u jarvis-task-worker.service
```

The service restarts after failure, has a 20-second stop budget, and stops its control group. Explicit stop stays stopped. It is separate from regular Jarvis daemons and their restart mechanisms. Starting it initializes storage with admission **off**; sign into Web, open Background tasks, check readiness, then enable the master switch and **Convert file** in **Settings → Tools → Background tasks**. The saved choices apply to subsequent Web text requests. Admission still requires a Web conversation and a saved source receipt; direct tool buttons settle this source turn without a model call.

## Optional Docker worker

The `extras` profile starts the worker alongside the other optional UIs. Core-only
deployments can start it separately with the retained `background-tasks` profile:

```bash
docker compose --profile background-tasks up -d --build jarvis-task-worker
docker compose logs --tail=50 jarvis-task-worker
docker compose stop jarvis-task-worker
```

The worker uses the same image, UID, config/data mounts and tool profile as Jarvis. It exposes no ports and has no daemon dependencies. It reads the Web tool-block configuration through a read-only bind; start the normal Web deployment first so `jarvis-web/config/web_config.json` exists. Its entrypoint skips initialization/tool synchronization and its healthcheck reports durable worker presence. `init: true` reaps children; a 20-second stop grace and `unless-stopped` policy provide isolated supervision. Start/stop of this service does not start/stop Web, API, Canvas, or existing daemons.

The stock Compose stack does not run the managed Browser Use helper: its setup and
callback submission are currently native-loopback paths. The Docker worker can
serve reviewed local/remote skill bindings, but Browser Use needs a separate
cross-container transport and lifecycle design. See the
[Docker guide](docker/README.md#background-tasks-and-task-callbacks).

## Shared local skill runner

`local_skill_v1` is the policy for process-contained work; `convert_file` is its production tool binding. The same runner also serves the three media generators, social clips, hosted Browser Use Cloud, Docling, and the optional Craft editing clients under `remote_skill_v1` (see below).

A compatible local skill needs its ordinary manifest/script, reviewed execution metadata, and one `TRUSTED_BINDINGS` entry in `lib/background_tasks/production.py`. No new Python execution wrapper is needed. The tool name binds to its same-named `.py` or `.sh` sibling in `skills/`; manifests cannot select arbitrary paths, dynamic imports, MCP, workflow, or discovery handlers. A durable Web authorization binds the original request, mode, conversation generation, selected tool, and exact manifest/script digests. Before launching, the runner checks these again, current profile/availability, and Web blocks. Those checks do not remove foreground tools from discovery.

Child environments are assembled from the job's mode. Tools with a trusted `CHILD_ENVIRONMENT_POLICIES` entry receive only their reviewed keys; tools without one inherit the exported worker environment. Reviewed deployment overrides (`STASH_DIR`, `JARVIS_TOOL_PROFILE`) and background limits (`JARVIS_BACKGROUND_DEADLINE`, `JARVIS_BACKGROUND_MAX_INPUT_BYTES`) use `JARVIS_OVERRIDE_*`. Mode secrets such as API keys stay at normal precedence and are not promoted above `export_config_environment`.

For example, a reviewed local skill can declare:

```json
{
  "execution": {
    "background": {
      "supported": true,
      "adapter": "local_skill_v1",
      "completion_scope": "process_group",
      "timeout_seconds": 900,
      "progress_label": "Processing file",
      "limits": {
        "memory_bytes": 2147483648,
        "file_bytes": 536870912,
        "input_bytes": 536870912,
        "output_bytes": 2097152
      }
    }
  }
}
```

The timeout is required, is an integer from 1 to 86400 seconds, and is stored in the admission so queue time counts. Admission uses the fresh authorized policy snapshot rather than a cached tool schema; the worker rechecks the admitted budget. The listed resource limits are the defaults; overrides must be positive integers, capped at 32 GiB address space, 8 GiB per file/input, and 16 MiB captured output. `input_bytes` is supplied as `JARVIS_BACKGROUND_MAX_INPUT_BYTES`; the skill must enforce it when opening inputs, as conversion does. The runner cannot infer every skill's inputs. The child enforces memory/file/CPU ceilings and the executor bounds captured output. `JARVIS_BACKGROUND_DEADLINE` is an absolute timestamp for inner waits; review each skill's own timeouts before binding it.

Arguments are validated against the manifest's JSON Schema using Draft 2020-12 with external retrieval disabled. Top-level undeclared arguments are rejected unless `additionalProperties` explicitly permits them. Optional `argument_constraints` adds runtime-only JSON Schema restrictions without changing provider parameters or descriptions. Conversion's source/format constraints live there. No Tool RAG resync is required for these metadata changes.

The local policy requires `dangerous: false`, `auto_approve: true`, and `network: false`, plus the reviewed `completion_scope: "process_group"` declaration. Review child processes, daemonization, side effects, timeout/resource needs, and cancellation evidence before adding a binding. A local process ending cannot prove that a submitted remote operation stopped; the remote policy below handles this uncertainty. The separate `http_callback_v1` adapter serves the opt-in [Browser Use](BROWSER-USE.md) binding and does not change this process policy. Resource limits and permission metadata are not an OS network or filesystem sandbox.

Phone calls use an exact named production permission policy for
`remote_skill_v1`, retaining `dangerous: true` and `auto_approve: false`. The
reviewed permission policy is fingerprinted alongside the script and manifest;
a manifest cannot grant this exception to itself or another tool. Only call
actions are admitted; phone status/list/contact checks remain foreground. See
[phone calls](tools/phone/PHONE_CALLS.md#optional-web-background-calls).

Workers advertise supervision capability even if a particular conversion backend is missing; the requested skill then reports its backend failure. Restart both Web and any running worker after updating, so new admissions and worker capability use the same adapter identity. Ensure the selected runtime environment has the updated requirements. Native tmux runs use `JARVIS_VENV` (default `~/jarvis-venv`); the repository `.venv` is a development/test environment and is not required by the launcher.

### Upgrading with existing jobs

Supervised skill jobs use `local_skill_v1` or `remote_skill_v1`. The older conversion-specific adapter is not supported. Worker upgrades never rewrite accepted policy fingerprints or replay started submissions. Finish pending work before changing skill scripts; queued jobs whose reviewed script/manifest changed fail closed before launch.

## Remote media generation

Enable the desired media tools in **Settings → Tools → Background tasks**. Adding a production binding never selects it automatically. Settings reports readiness per tool; keep Web and the task worker on the same code and restart both after upgrades. Typed chat uses the same saved policy. Existing single-attempt-per-message guards for `generate_image`, `generate_video`, and `generate_music` apply; `create_social_clip` uses the exact-duplicate guard and may receive distinct arguments in separate calls.

These are still local skill subprocesses, sharing the same executor, supervision, argument validation, policy fingerprints, deadlines and durable delivery. Their manifests select `remote_skill_v1`, `completion_scope: "remote_work"`, and `network: true`; the trusted binding must independently select the same policy. There is one shared runner, not a Python wrapper for each generator. The original scripts retain their provider calls, generated-media catalogs, stash references and memory writes. Provider polling, where used, happens inside the worker's skill process while Web chat is free.

| Tool | Total background budget | Completion boundary |
| --- | --- | --- |
| `generate_image` | 900 seconds | Gemini/OpenAI/xAI requests return generated images, then the script saves files and references. |
| `generate_video` | 1200 seconds | xAI SDK polling and Gemini operations/interactions can keep generating after the observing process exits; the script waits for output and saves it. |
| `generate_music` | 2100 seconds | ElevenLabs HTTP generation (up to 1800 seconds for a ten-minute track) and Gemini interactions return audio, then the script saves it. |
| `create_social_clip` | 2100 seconds | MoneyPrinterTurbo owns a submitted job; the script polls its task ID, downloads the first completed video, and saves it to stash. A local stop cannot cancel the server job. |
| `phone_call` | 1200 seconds | One outbound call, Vapi status polling and best-effort Stash/Canvas collection. Only terminal provider results finish the job; stopping observation does not hang up the call. |
| `craft_image`, `craft_pdf`, `craft_photos`, `craft_video`, `craft_motion` | 1500 seconds | Craft Gateway owns durable jobs. The client observes for up to 1200 seconds and saves verified outputs. Inspect/collect or cancel through `craft_inspect`; stopping the observer does not cancel remote work. |

Queue time counts toward these budgets. The three generators and social clips use a 4 GiB process address-space ceiling, 512 MiB per output file and 2 MiB captured-output limit. `save: false` is rejected for background media so successful replies can retain artifacts. Input resource metadata does not itself validate every reference/download; the skill loaders and process ceilings still apply. Background selection does not extend an individual provider request timeout.

Social clips require `MONEYPRINTER_API_URL` in the selected mode. Background arguments require a nonempty subject, cap subject/script at 20,000 characters, validate the documented 1–10 paragraphs and positive clip duration, and restrict `video_count` to 1 because the skill only saves the first returned video. The 35-minute budget allows room for its default 20-minute poll, creation waits and download; increasing `MONEYPRINTER_MAX_WAIT_SEC` does not extend the admitted budget. Existing queue-full (429) submission retries remain inside the skill. Jarvis never replays an uncertain attempt. These four media tools, Browser Use Cloud, Docling, and the five Craft editing clients share the `remote_skill_v1` capacity bucket; uncertain attempts also occupy global running capacity, including capacity otherwise available for conversion.

These are upper observation budgets, not extensions of a provider/SDK's individual request timeouts. Existing provider waits still apply; a lost response after launch takes the uncertain-outcome path below.

The outcome contract is deliberately conservative:

- A confirmed `ok: true` result commits with its follow-up normally. Manifest/schema/authorization failures before launch are known failures.
- Trusted skill failures may return `ok: false` with `completion: "rejected"` (explicit submission rejection) or `completion: "completed"` (provider work reached a terminal response, including a failure, or finished before local saving failed). The shared runner saves these as bounded failed results, releases capacity and delivers the error. It never resubmits them.
- Missing/unknown completion evidence, malformed responses, polling errors, timeouts, output loss, shutdown and killed workers remain **needs attention**, reserve capacity and are never automatically replayed. Error prose is never treated as proof. In particular, a quota error while polling an accepted job does not prove it stopped.
- `lib/remote_completion.py` carries this evidence from reviewed provider boundaries. Background xAI video uses separate SDK submission/polling calls with SDK resubmission disabled. Background Gemini Interactions uses public HTTP hooks to stop error responses before SDK retries and refuse a second submission after a lost response; polling remains independent. Gemini submission errors and explicit terminal results, synchronous image/music HTTP rejections, and MoneyPrinterTurbo rejected submissions/failed tasks provide evidence. Unclassified failures remain conservative.
- Queued cancellation prevents dispatch. Running remote jobs have no Cancel action/API permission because process-group termination only proves the local observer stopped. Operator reconciliation requires evidence that the provider operation has settled; stopping Jarvis alone is insufficient.

The shared remote skill policy does not resume remote job IDs, implement provider cancellation, or receive callbacks. Those require a separately reviewed completion/recovery contract; [Apify](mcp/APIFY.md) has one under `apify_actor_v1`, without changing these remote skill bindings. `transcribe_audio`, `document_ocr`, `analyze_video`, and `analyze_image` have no background bindings.

## Concurrent artifacts and operator revisions

Image, video and audio catalogs use one shared cross-process lock around complete read/modify/replace operations. Generator upserts, gallery reconciliation, favorites and local catalog deletion participate in that lock. Generated images (including batches), videos, music and social clips use UUID-suffixed filenames so matching prompts finishing in the same second do not overwrite files.

Canvas gallery labels hide the generation timestamp and UUID. The stored filename remains the catalog/CDN key and is used unchanged for file URLs, downloads, sharing and deletion; formatting a label never renames a file or migrates a catalog.

Job revisions track semantic changes rather than heartbeat/lease renewal. A heartbeat does not invalidate a Cancel token or rewrite a task card; progress, state, read status and delivery changes still advance revisions. Keep Web, worker, Canvas and API on the same version so every catalog writer participates in the shared lock.

Continuation stash links, media previews and the stash viewer carry the original job's mode through raw/open/download requests. Legacy links with no explicit mode retain their previous behavior.

Provider protocol references: [Gemini structured errors](https://ai.google.dev/gemini-api/docs/api-errors) and [xAI deferred video generation](https://docs.x.ai/developers/model-capabilities/video/generation).

## Conversion boundary and limits

The adapter reuses the foreground executor's local subprocess seam, including timeout, proxy policy, progress, permissions, and session context. Each local skill has a private temporary workspace and explicit mode environment. The parent checks ownership/deadline/shutdown/cancellation roughly every 250 ms while running. Termination escalates TERM to KILL and verifies the whole process group; the Linux child also watches for worker death. The task inspector records the process/group IDs as progress evidence. Unverifiable termination reserves the slot.

Input is limited to 512 MiB, each output file to 512 MiB, each child address space to 2 GiB, and captured process output to 2 MiB. A known conversion failure that exceeds the 1 MiB stored-result cap keeps a bounded diagnostic excerpt (beginning and end) with an explicit truncation marker. It commits as failed with its follow-up queued and releases execution capacity; it does not become uncertain merely because ffmpeg printed a large error.

Background conversion uses the remaining admitted job budget (900 seconds by default), including time already spent queued or preparing. The supervisor and each conversion subprocess share that absolute deadline, so sequential stages do not reset the clock. The CPU allowance scales with CPUs in the child's affinity mask because CPU time is summed across ffmpeg threads; wall-clock supervision still enforces the job deadline. Foreground conversion retains its 180-second executor timeout and its existing inner waits. Graceful local stops release capacity once the supervisor verifies termination. Lease expiry alone, a killed worker with no surviving reporter, or unverifiable termination still reserves capacity for reconciliation; recovery never guesses from a stored PID or replays an attempt.

These are process/file ceilings, not a container-wide memory quota. Configure container/host quotas separately for aggregate limits. Files already created in stash may survive an uncertain execution and must not be inferred absent from a cancelled/failed card. A killed worker can leave an isolated temporary workspace; inspect its recorded process group before cleaning that job's workspace. Never delete the task database to clear an uncertain slot.

PDF conversion is not supported by this adapter. Incoming callbacks have a
separate authenticated [service protocol](TASK-CALLBACKS.md#self-hosted-protocol).
A private long-task binding needs a packaged and verified completion POST
contract for that deployment. A public relay is not included or required for
local background execution.

### Optional Craft editing clients

`craft_image`, `craft_pdf`, `craft_photos`, `craft_video` and `craft_motion`
use reviewed `remote_skill_v1` bindings with a 1500-second worker budget and
1200-second client observation budget. The optional gateway owns the work.
Foreground calls observe for up to 110 seconds and can return an honest running
receipt; `craft_inspect` checks job/request IDs, collects outputs or requests
remote cancellation. Stopping the observer does not cancel its gateway job.
Lost submissions query their persisted request ID instead of replaying a POST;
unknown outcomes retain existing remote-task uncertainty semantics. Each client
has a separate trusted restricted background environment; no other provider
credentials are passed. See [Craft setup and troubleshooting](../jarvis-craft-tools/README.md).

## Contributor checks

From the repository root:

```bash
.venv/bin/python -m pytest tests/test_background_tasks.py tests/test_background_task_delivery.py tests/test_background_conversion.py tests/test_background_local_skill.py tests/test_background_remote_skill.py tests/test_web_background_tasks.py tests/test_web_background_handoff.py tests/test_web_background_context.py tests/test_web_background_media.py -q
.venv/bin/python -m pytest tests/test_background_task_management.py tests/test_background_task_deployment.py tests/test_background_task_workflow.py tests/test_background_review_regressions.py tests/test_web_background_tasks_ui.py tests/test_web_continuation_rendering.py -q
```

These checks use disposable storage and scripted model/provider responses.
Conversion checks exercise real local conversion binaries. JavaScript checks use
Node and do not replace a browser/device check. Use [the full core suite](TESTING.md)
for cross-component regression checks; Firefox extension tests have their own
command.

An optional long-encode check paces a generated looping video beyond the
foreground tool timeout and validates its output:

```bash
JARVIS_TEST_LONG_ENCODE=1 .venv/bin/python -m pytest tests/test_background_conversion.py::test_background_video_encode_survives_foreground_timeout -q -s
```

Optional `JARVIS_TEST_VIDEO` / `JARVIS_TEST_IMAGE` paths enable representative
media checks using temporary copies and disposable outputs. See
[callback contributor checks](TASK-CALLBACKS.md#isolated-acceptance-proof) for the
local HTTP protocol fixture and its socket permission requirement.
