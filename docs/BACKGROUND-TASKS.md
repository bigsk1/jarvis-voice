# Background tasks

Web task management uses a supervised skill runner with two reviewed policies: `local_skill_v1` for `convert_file`, and `remote_skill_v1` for `generate_image`, `generate_video`, `generate_music`, and `create_social_clip`. The separate `http_callback_v1` adapter submits `browser_use` to its local service and accepts completion through an authenticated callback. Tools enabled in **Settings → Tools → Background tasks** return an acceptance receipt, release the chat turn, run outside chat, and deliver a saved card and follow-up answer to the same conversation. You can send another message and call another tool while the job runs.

**Browser Use is Web-only and background-only.** It requires the saved allowlist, worker and callback service. Unmet requirements hide it from model selection; stale or forced calls fail without starting browser work. Voice, Talk, Firefox Companion, query API, CLI and workflows cannot run it; there is no foreground fallback.

For tools declaring `execution.background.required`, runtime discovery adds unmet background/callback requirements to the existing request block list. The tool can remain enabled and indexed while hidden from Tool RAG selection, exact tool lookup and model schemas. Callback tools require an enabled receiver and trusted source with a successful setup test, usable credentials/key storage, and success/failure events. These read-only checks never edit the saved manual block list or create jobs. Web computes readiness once per turn and shares it across routing and Tool RAG; selected tools hidden by AdmissionDenied log the reason. Admission rechecks live policy before queueing; the worker checks again before submission. Ordinary conversion/media tools retain their existing foreground availability. This does not require a Tool RAG resync when toggling settings.

**Background admission and incoming webhooks default off; the saved tool list starts empty.** Execution requires a running Linux worker and saved Web preferences. The native start-all and UI groups start that worker; admission remains opt-in. Importing the package creates no storage or service. Missing workers affect background readiness only. An enabled background call reports unavailability rather than silently running foreground; unrelated chat and foreground tools keep working.

Local conversion needs no Tailscale network, VPS, or public endpoint. [Task callbacks](TASK-CALLBACKS.md) add an optional authenticated inbox and **Settings → Integrations** controls, proven with a separate local HTTP service. The opt-in [Browser Use](BROWSER-USE.md) tool is the first callback binding; a long-running Samantha callback binding and the standalone relay remain later phases. The existing short foreground `samantha` tool is separate. OpenCode and `/api/alerts` are outside this work. Firefox source compatibility is tested in-tree; packaging and AMO release remain separate steps.

## Run the isolated proof

From the repository root:

```bash
.venv/bin/python -m pytest tests/test_web_startup_imports.py tests/test_background_tasks.py tests/test_background_task_delivery.py tests/test_background_task_management.py tests/test_background_task_deployment.py tests/test_background_task_workflow.py tests/test_background_conversion.py tests/test_background_local_skill.py tests/test_web_background_tasks.py tests/test_web_background_handoff.py tests/test_web_background_context.py tests/test_web_background_tasks_ui.py tests/test_mode_plumbing_scripts.py -q
.venv/bin/python -m pytest tests/test_web_continuation_rendering.py tests/test_web_assistant_message_rendering.py tests/test_web_response_actions.py tests/test_web_task_recovery.py tests/test_web_task_recovery_ui.py tests/test_completion_guard_server_side_tools.py -q
.venv/bin/python -m pytest tests/test_background_review_regressions.py tests/test_background_remote_skill.py tests/test_web_background_media.py -q
node --test jarvis-firefox-extension/tests/client.test.js jarvis-firefox-extension/tests/ui-rendering.test.js jarvis-firefox-extension/tests/talk.test.js
```

The Python tests use temporary SQLite databases, conversation JSON, configuration, and artifact directories. A real Flask-SocketIO test client drives the actual Web handler, orchestrator loop, executor, conversation lease, and local worker process. The model's routing decisions and summary are scripted; no provider credentials, live services, or network listener are used. Browser state/rendering tests execute the shipped JavaScript in a Node VM; they are not a manual browser acceptance run.

The worker startup tests cover normal and `python -I` launches from outside the checkout, including health, singleton ownership, and clean shutdown. The Web startup tests also run the complete Web launcher and app factory in fresh isolated Python processes from outside the checkout. They exercise real route imports and handler construction without pytest's repository import path; configuration, storage, logs, and the network listener are isolated.

The principal journey runs in both cloud and local modes:

1. Save the inert fixture in the background tool list and send the first Web message without a per-message selection.
2. Persist its acceptance answer and pending card; finish the source run and release its lease before the worker starts.
3. Send a second message that calls an actual local foreground subprocess.
4. Finish the background fixture while that second tool is active. Its original card updates immediately; its follow-up answer waits for the conversation lease.
5. Finish the foreground turn, append exactly one late assistant answer, and reconnect to recover both the card and answer. No synthetic user message is added.

The explicit Convert test sends known PNG→JPEG arguments without constructing the orchestrator, settles its receipt, and runs another foreground tool while a real conversion child is paused. It then releases ImageMagick and decodes the resulting JPEG. A separate test pauses late answer generation, sends a new foreground turn, and verifies that stale prose is regenerated against the new history. Both use isolated storage and scripted model responses.

Each subsequent chat turn receives a bounded task-store snapshot for its conversation generation across both modes, including after new admissions are disabled. Each job retains its original execution mode; switching chat mode does not hide its status or change execution/delivery authorization. Evidence includes the last reported progress, update time, and attention reason when available. Execution state and answer-delivery state stay separate: a finished tool can still have a pending follow-up answer. Current facts supersede old receipt prose; unrelated replies should not recap jobs. Foreground context and late answers share explicitly labeled input arguments and returned results, so a newly created output artifact is not mistaken for a mismatched input solely because its stash identifiers differ.

The eight-job snapshot prioritizes unfinished/uncertain work, then pending answer delivery, then recent terminal outcomes. Cancelled and expired jobs have terminal rank; they do not displace newer successes as unfinished work. Expiry means a job missed its admission deadline without dispatch; result archival is a separate retention flag.

Failure tests cover missing receipt writes, unsaved source outcomes, source-history recovery during a successor turn, stale ownership, summary/projection failure, restart, deletion fencing, retention, disabled admission, authentication, and isolation from Completion Guard and unsupported callers. Each crash scenario has its own database; uncertain work never gets replayed to make a test pass.

`tests/fixtures/background_task_worker.py` is absent from tool discovery and production profiles. The test harness supplies its trusted adapter binding and output root. Its exclusive `.started` artifact detects repeat execution.

## Admission and execution

Tool manifests may declare capability outside the provider's parameter schema:

```json
{"execution": {"background": {"supported": true, "adapter": "reviewed_adapter_name"}}}
```

This metadata grants no execution authority. A matching trusted adapter binding, healthy worker, enabled admission, and server-created Web authorization are required. Unknown metadata or unavailable workers disable background admission without hiding an otherwise available foreground tool. `execution.background.required: true` additionally forbids foreground execution; Browser Use declares this requirement. There is no model-controlled `execution_mode` parameter or inherited background context for nested workflow steps.

The server snapshots the saved tool list for each authenticated Web text request. Background-only tools get a read-only eligibility check before model selection. An actual selected call validates current capability, policy and blocks again. Authorization and the held job are saved atomically; unrelated turns create no authorization rows. Authorization records the conversation generation, source request, mode, allowed tool, policy fingerprints, and original provider/model. It does not copy user text: late answers read the original request from the conversation. The admission transaction rechecks both the master switch and tool membership, so unchecking a tool prevents new jobs even if routing already began. Client-supplied `background_tools` cannot grant or override permission. The executor receives the context explicitly for top-level Web invocations. Talk, Firefox Companion, voice/CLI, query API, schedules, and workflow steps keep ordinary foreground tools, reject background-only tools, and reject leaked background receipts instead of treating them as completed work.

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

A matching slash-workflow command takes precedence and runs its ordinary foreground pipeline. Saved background preferences are not inherited by workflow steps. The unsupported-caller guard also recognizes `status=accepted` plus `job_id` as a leaked receipt; it deliberately accepts that broader signal as well as the typed `background_admission` marker.

Adapters receive `ExecutionContext`, use its mode environment for children, and check ownership/deadline/shutdown during cooperative work. A returned result means completion is known; `KnownFailure` means known unsuccessful completion. Unexpected errors and interruption without termination proof produce `needs_attention` without automatic execution retry. A surviving local supervisor can report verified process-group termination for its exact attempt after shutdown or lease/deadline expiry. That settles as failed (or cancelled if cancellation was requested) and releases capacity. This report cannot overwrite an operator disposition or cross a conversation-disposal fence. Remote work remains uncertain after stopping its local observer.

**A `needs_attention` job with an `attempt_id` still reserves a running slot.** Clearing a conversation or stopping a worker is not proof that the operation stopped. The task inspector requires an explicit stopped-operation attestation, evidence, and failed/cancelled disposition before releasing this capacity. The evidence and state change commit together; reconciliation never replays execution.

## Delivery and recovery

The Web coordinator drains on startup and every second. One process owns its lock for a task database. It observes active attempts, pages other job updates, recovers held receipts, and attempts pending deliveries. SQLite write transactions never span model generation; final projection holds a short fence transaction through atomic conversation JSON replacement.

If another Web process owns that lock, startup continues with foreground chat available. The losing process reports coordinator unavailability and refuses background admission or enabling; it can still disable new admission. It does not start a second drain loop. A later start/status request can acquire ownership once the previous coordinator releases the lock.

Task-store corruption, incompatible schema, or inaccessible storage must not hide conversation JSON or abort ordinary chat. Conversation reads log an unavailable fence lookup and skip task-fence recovery until storage is repaired. Admission, delivery, disposal, and import protections still fail closed. If preferences cannot be read, calls to reviewed background-capable tools return an availability error rather than silently launching inline; unrelated chat/tools remain usable. Coordinator initialization failure also leaves Web serving chat.

After a delivery transaction commits or defers, Web republishes the source card with the current outbox revision. A late answer therefore clears “reply pending” without another user message or reliance on the timestamp paging cursor. Restart recovery still restores cards and the saved continuation.

Normal chat status questions receive the current delivery state separately from the tool's execution state. Late-answer generation omits that internal delivery state: the answer being composed is itself the result delivery message, so it must not describe its own result as still awaiting delivery. This does not mark delivery complete early; the outbox changes to `delivered` only when projection commits.

The schema update removes legacy query copies from authorization payloads without changing accepted job identities or execution fingerprints. Clear/delete removes authorizations for the disposed generation. Result retention also removes old orphan authorizations and authorizations whose referencing results have all been archived; active work and pending follow-ups keep the metadata they need. Restart both Web and worker when applying this schema update.

A continuation has its own delivery lease (30 seconds, renewed every five), stable ID, parent job/request, and `kind=continuation`. It snapshots idle conversation history under the mode gate, then generates with the original provider/model and all tools disabled **without holding the chat lease**. New foreground messages can run while generation is in progress. It takes the conversation lease only for the brief append/settlement step. It does not invoke the orchestrator or repair loop. At most two deliveries generate concurrently, with one per conversation.

The generated answer is cached in the outbox before JSON projection. Projection retries reuse that output when its saved history fingerprint still matches. If another message changed the history during generation or a delivery retry, the coordinator discards only the generated prose and summarizes again after foreground chat settles. Already projected continuation IDs recover without regeneration. A saved continuation ID prevents duplicate messages when JSON replacement succeeds but the outbox commit fails. Model failures defer delivery with bounded backoff; the completed tool result remains accessible with a “reply delayed” status. A process death during generation may repeat the summary call after expiry, but never authorizes another tool execution.

`task:updated` revises the original card; `chat:continuation` appends the late answer. They use a separate authenticated `tasks:<conversation>` subscription and never emit legacy `tool:*` or `chat:response` events. Revision and generation checks reject stale events. Web and Firefox preserve foreground progress, Stop state, drafts, attachments, and Talk audio. Saved conversation history restores missed events.

Live and restored Web continuations use a separate DOM renderer. Markdown formatting remains readable; raw HTML is literal text, and links accept HTTP(S) or fully parsed, encoded stash references. Successful tool results with saved media now show inline image previews (with the existing lightbox), video controls, or audio controls, plus Open/Download actions. The shared media renderer uses the existing media styles and builds DOM nodes from structured results; it never feeds late data into legacy HTML widgets or rich-content hydration. Media loads only from encoded same-origin stash URLs, with no autoplay or provider URL fallback. Unsupported files retain viewer links, and failed previews keep their file actions.

New continuations persist their job's execution mode for stash URLs. Older saved replies recover it from the source receipt card without rewriting conversation history, so a later chat-mode switch does not select the wrong stash. Each continuation has response-only Copy; it preserves the current foreground action rail. Trailing continuations do not change that answer's reaction eligibility, while a later user message still invalidates it.

Ordinary clear/delete refuses outstanding work. Explicit disposition fences the generation and suppresses pending delivery before clearing/deleting JSON. The durable fence completes recovery if the JSON operation fails afterward. Retention preserves outstanding jobs, fails closed on task-store errors, and its dry run makes no changes. Imports cannot overwrite pending destinations or deleted IDs.

## Web controls and authentication

**Settings → Tools → Background tasks** contains the master switch and saved list of tools allowed to run in the background. Changes save immediately and apply to Web text chat and tool dialogs in both modes, across messages, tabs, reloads, and restarts. The composer has no background checkboxes. Preferences can be saved while the worker is offline; readiness is shown separately.

**Browser Use has one normal setup action in this same panel.** Click **Set up and enable** once. Jarvis checks Docker, downloads the pinned optional image when needed, provisions and verifies its private callback source, enables the receiver and saved tool permission, and starts the managed tmux helper. Setup returns immediately while Settings polls progress; a second click joins the same attempt, and interrupted setup can be retried. The Integrations tab keeps advanced callback and delivery controls; it is not part of the normal Browser Use setup. Afterward the usual Start All groups manage the helper automatically.

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

Web starts its coordinator only when task storage exists or an authenticated operator explicitly initializes controls. An unstarted admission that reaches its deadline becomes **expired**, without executing. A started attempt whose ownership/deadline expires becomes **needs attention** unless its surviving local supervisor reports verified termination for that attempt. Cancellation and expiry are persisted flags over the existing physical state constraint, preserving old task databases without a destructive table rebuild.

Every hour, the coordinator archives at most 100 old terminal result/progress payloads and cached follow-up outputs. Active/uncertain jobs and pending follow-ups are protected. Invocation identities, admission records, attempt history, and operator evidence remain; a repeated identity cannot execute again after archival. Conversation messages and stash artifacts are untouched. Archived payloads cannot be retried. The UI preview makes no writes. This is result-payload retention, not deletion of conversation history or a backup compaction policy.

## Native worker

The task store uses SQLite WAL mode with short-lived connections. `background_tasks.db-wal` and `background_tasks.db-shm` can appear during access and disappear when the last connection closes. The worker and Web drain check frequently, so this can cause IDE Explorer flicker even while idle. SQLite manages these files; they are already ignored by Git. An IDE Explorer exclusion for `**/*.db-wal` and `**/*.db-shm` can hide the visual churn without changing storage behavior.

After updating the checkout, restart Web so it loads the new task routes and adapter binding. Use Linux with the normal Jarvis runtime environment (`JARVIS_VENV`, default `~/jarvis-venv`) and local conversion binaries. Audio/video conversion needs ffmpeg; images need ImageMagick; raster-to-SVG additionally needs Potrace. Missing backends produce a truthful failed result for the requested conversion.

To inspect status or run the worker in a terminal:

```bash
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker status
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-worker run
```

**Tmux is the current native development and operating workflow.** It makes it easy to start, stop, attach to, and debug the whole application while features are evolving. Systemd is an optional future installation path once the system is stable; it is not required or installed by the normal startup commands.

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
upload is enabled by this feature. Restart Web and worker to load the logging code.

### Optional future systemd installation

Keep the unit generator available for a future stable deployment. These are manual opt-in installation commands, not steps required for the current tmux workflow. To use automatic restarts independent of tmux, generate and inspect the portable systemd user unit, then install it:

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

The ordinary Compose services are unchanged when the profile is absent:

```bash
docker compose --profile background-tasks up -d --build jarvis-task-worker
docker compose logs --tail=50 jarvis-task-worker
docker compose stop jarvis-task-worker
```

The worker uses the same image, UID, config/data mounts and tool profile as Jarvis. It exposes no ports and has no daemon dependencies. It reads the Web tool-block configuration through a read-only bind; start the normal Web deployment first so `jarvis-web/config/web_config.json` exists. Its entrypoint skips initialization/tool synchronization and its healthcheck reports durable worker presence. `init: true` reaps children; a 20-second stop grace and `unless-stopped` policy provide isolated supervision. Start/stop of this service does not start/stop Web, API, Canvas, or existing daemons.

Compose rendering and isolation are tested; building/running this optional container remains an operator deployment step. Native worker execution is exercised with real disposable stores.

The stock Compose stack does not run the managed Browser Use helper: its setup and
callback submission are currently native-loopback paths. The Docker worker can
serve reviewed local/remote skill bindings, but Browser Use needs a separate
cross-container transport and lifecycle design. See the
[Docker guide](docker/README.md#background-tasks-and-task-callbacks).

## Shared local skill runner

`local_skill_v1` is the policy for process-contained work; `convert_file` remains its only production tool binding. The same runner also serves the three media generators and social clips under `remote_skill_v1` (see below). The [implementation plan](personal/background-tasks-and-webhook-integrations-plan.md#phase-2-follow-up-generic-local-skill-runner) tracks the extraction and its gate. The inert local probe lives only in `tests/fixtures/local_skill_probe.*` and runs from a temporary installation, with no production discovery or saved preference changes.

A compatible local skill needs its ordinary manifest/script, reviewed execution metadata, and one `TRUSTED_BINDINGS` entry in `lib/background_tasks/production.py`. No new Python execution wrapper is needed. The tool name binds to its same-named `.py` or `.sh` sibling in `skills/`; manifests cannot select arbitrary paths, dynamic imports, MCP, workflow, or discovery handlers. A durable Web authorization binds the original request, mode, conversation generation, selected tool, and exact manifest/script digests. Before launching, the runner checks these again, current profile/availability, and Web blocks. Those checks do not remove foreground tools from discovery.

Child processes receive the job's mode file as ordinary environment keys. Only reviewed deployment overrides (`STASH_DIR`, `JARVIS_TOOL_PROFILE`) and background limits (`JARVIS_BACKGROUND_DEADLINE`, `JARVIS_BACKGROUND_MAX_INPUT_BYTES`) are stamped as `JARVIS_OVERRIDE_*`. Mode secrets such as API keys stay at normal precedence and are not promoted above `export_config_environment`.

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

The local policy requires `dangerous: false`, `auto_approve: true`, and `network: false`, plus the reviewed `completion_scope: "process_group"` declaration. Review child processes, daemonization, side effects, timeout/resource needs, and cancellation evidence before adding a binding. A local process ending cannot prove that a submitted remote operation stopped; the remote policy below handles this uncertainty. OpenCode and long-running Samantha tasks remain deferred. The separate `http_callback_v1` adapter serves the opt-in [Browser Use](BROWSER-USE.md) binding and does not change this process policy. Resource limits and permission metadata are not an OS network or filesystem sandbox.

Workers advertise supervision capability even if a particular conversion backend is missing; the requested skill then reports its backend failure. Restart both Web and any running worker after updating, so new admissions and worker capability use the same adapter identity. Ensure the selected runtime environment has the updated requirements. Native tmux runs use `JARVIS_VENV` (default `~/jarvis-venv`); the repository `.venv` is a development/test environment and is not required by the launcher.

### Existing conversion jobs

The pre-extraction conversion alias and fingerprint bridge have been removed after verifying the installation has no legacy jobs. New jobs use `local_skill_v1` or `remote_skill_v1`. Worker upgrades never rewrite accepted policy fingerprints or replay started attempts. Finish pending work before changing skill scripts; queued jobs whose reviewed script/manifest changed fail closed before launch.

## Remote media generation

Restart Web **and the task worker** after installing this change, then enable the desired media tools in **Settings → Tools → Background tasks**. Existing preferences are preserved; adding production bindings never selects tools automatically. Settings reports readiness per tool, so an older worker that only supports conversion cannot claim media readiness. Typed chat uses the same saved policy. Existing single-attempt-per-message guards for `generate_image`, `generate_video`, and `generate_music` remain; `create_social_clip` uses the existing exact-duplicate guard and may receive distinct arguments in separate calls.

Run the isolated media proof from the repository root:

```bash
.venv/bin/python -m pytest tests/test_background_remote_skill.py tests/test_web_background_media.py -q
```

These are still local skill subprocesses, sharing the same executor, supervision, argument validation, policy fingerprints, deadlines and durable delivery. Their manifests select `remote_skill_v1`, `completion_scope: "remote_work"`, and `network: true`; the trusted binding must independently select the same policy. There is one shared runner, not a Python wrapper for each generator. The original scripts retain their provider calls, generated-media catalogs, stash references and memory writes. Provider polling, where used, happens inside the worker's skill process while Web chat is free.

| Reviewed tool | Total background budget | Provider boundary reviewed |
| --- | --- | --- |
| `generate_image` | 900 seconds | Gemini/OpenAI/xAI requests return generated images, then the script saves files and references. |
| `generate_video` | 1200 seconds | xAI SDK polling and Gemini operations/interactions can keep generating after the observing process exits; the script waits for output and saves it. |
| `generate_music` | 2100 seconds | ElevenLabs HTTP generation (up to 1800 seconds for a ten-minute track) and Gemini interactions return audio, then the script saves it. |
| `create_social_clip` | 2100 seconds | MoneyPrinterTurbo owns a submitted job; the script polls its task ID, downloads the first completed video, and saves it to stash. A local stop cannot cancel the server job. |

Queue time counts toward these budgets. All four use a 4 GiB process address-space ceiling, 512 MiB per output file and 2 MiB captured-output limit. `save: false` is rejected for background media so successful replies can retain artifacts. Input resource metadata does not itself validate every reference/download; the existing skill loaders and process ceilings still apply. No provider API, price, model default or foreground timeout changes are part of this binding review.

Social clips require `MONEYPRINTER_API_URL` in the selected mode. Background arguments require a nonempty subject, cap subject/script at 20,000 characters, validate the documented 1–10 paragraphs and positive clip duration, and restrict `video_count` to 1 because the skill only saves the first returned video. The 35-minute budget allows room for its default 20-minute poll, creation waits and download; increasing `MONEYPRINTER_MAX_WAIT_SEC` does not extend the admitted budget. Existing queue-full (429) submission retries remain inside the skill. Jarvis never replays an uncertain attempt. All four remote tools share the `remote_skill_v1` capacity bucket, and uncertain attempts also occupy global running capacity, including capacity otherwise available for conversion.

These are upper observation budgets, not extensions of a provider/SDK's individual request timeouts. Existing provider waits still apply; a lost response after launch takes the uncertain-outcome path below.

The outcome contract is deliberately conservative:

- A confirmed `ok: true` result commits with its follow-up normally. Manifest/schema/authorization failures before launch are known failures.
- Trusted skill failures may return `ok: false` with `completion: "rejected"` (explicit submission rejection) or `completion: "completed"` (provider work reached a terminal response, including a failure, or finished before local saving failed). The shared runner saves these as bounded failed results, releases capacity and delivers the error. It never resubmits them.
- Missing/unknown completion evidence, malformed responses, polling errors, timeouts, output loss, shutdown and killed workers remain **needs attention**, reserve capacity and are never automatically replayed. Error prose is never treated as proof. In particular, a quota error while polling an accepted job does not prove it stopped.
- `lib/remote_completion.py` carries this evidence from reviewed provider boundaries. Background xAI video uses separate SDK submission/polling calls with SDK resubmission disabled. Background Gemini Interactions uses public HTTP hooks to stop error responses before SDK retries and refuse a second submission after a lost response; polling remains independent. Gemini submission errors and explicit terminal results, synchronous image/music HTTP rejections, and MoneyPrinterTurbo rejected submissions/failed tasks provide evidence. Unclassified failures remain conservative.
- Queued cancellation prevents dispatch. Running remote jobs have no Cancel action/API permission because process-group termination only proves the local observer stopped. Operator reconciliation requires evidence that the provider operation has settled; stopping Jarvis alone is insufficient.

The shared remote policy does not resume remote job IDs, implement provider cancellation, or receive callbacks. Those require a provider-specific completion/recovery contract later. `transcribe_audio`, `document_ocr`, `analyze_video`, and `analyze_image` are not added to the background allowlist by this review.

`tests/test_background_remote_skill.py` checks policy separation, uncertain outcomes, prelaunch rejection (including tool blocks changed after admission) and an independent provider fixture that completes after its local observer stops. `tests/test_web_background_media.py` runs the actual three generator CLI/save paths and social-clip submit/poll/download/stash path with scripted providers in both modes, using temporary artifacts/catalogs/stash and a live-write guard. It proves receipt → second foreground tool → saved artifact/late answer, plus mode-specific profile, ENV, manifest and Web blocking. The video bytes are fixture responses, not encoded provider videos. No paid API calls are used.

## Concurrent artifacts and operator revisions

Image, video and audio catalogs use one shared cross-process lock around complete read/modify/replace operations. Generator upserts, gallery reconciliation, favorites and local catalog deletion participate in that lock. Generated images (including batches), videos, music and social clips use UUID-suffixed filenames so matching prompts finishing in the same second do not overwrite files.

Canvas gallery labels hide the generation timestamp and UUID. The stored filename remains the catalog/CDN key and is used unchanged for file URLs, downloads, sharing and deletion; formatting a label never renames a file or migrates a catalog.

Schema migration 7 makes job revisions track semantic changes instead of heartbeat/lease renewal. A heartbeat does not invalidate a Cancel token or rewrite a task card; progress, state, read status and delivery changes still advance revisions. Restart Web and worker together to apply the migration. Restart Canvas/API as well when deploying the shared catalog lock so every writer participates.

Continuation stash links, media previews and the stash viewer carry the original job's mode through raw/open/download requests. Legacy links with no explicit mode retain their previous behavior. Refresh Web after deploying these scripts.

Provider protocol references: [Gemini structured errors](https://ai.google.dev/gemini-api/docs/api-errors) and [xAI deferred video generation](https://docs.x.ai/developers/model-capabilities/video/generation). Tests use scripted providers; no live provider requests are needed for these changes.

## Conversion boundary and limits

The adapter reuses the foreground executor's local subprocess seam, including timeout, proxy policy, progress, permissions, and session context. Each local skill has a private temporary workspace and explicit mode environment. The parent checks ownership/deadline/shutdown/cancellation roughly every 250 ms while running. Termination escalates TERM to KILL and verifies the whole process group; the Linux child also watches for worker death. The task inspector records the process/group IDs as progress evidence. Unverifiable termination reserves the slot.

Input is limited to 512 MiB, each output file to 512 MiB, each child address space to 2 GiB, and captured process output to 2 MiB. A known conversion failure that exceeds the 1 MiB stored-result cap keeps a bounded diagnostic excerpt (beginning and end) with an explicit truncation marker. It commits as failed with its follow-up queued and releases execution capacity; it does not become uncertain merely because ffmpeg printed a large error.

Background conversion uses the remaining admitted job budget (900 seconds by default), including time already spent queued or preparing. The supervisor and each conversion subprocess share that absolute deadline, so sequential stages do not reset the clock. The CPU allowance scales with CPUs in the child's affinity mask because CPU time is summed across ffmpeg threads; wall-clock supervision still enforces the job deadline. Foreground conversion retains its 180-second executor timeout and its existing inner waits. Graceful local stops release capacity once the supervisor verifies termination. Lease expiry alone, a killed worker with no surviving reporter, or unverifiable termination still reserves capacity for reconciliation; recovery never guesses from a stored PID or replays an attempt.

These are process/file ceilings, not a container-wide memory quota. Configure container/host quotas separately for aggregate limits. Files already created in stash may survive an uncertain execution and must not be inferred absent from a cancelled/failed card. A killed worker can leave an isolated temporary workspace; inspect its recorded process group before cleaning that job's workspace. Never delete the task database to clear an uncertain slot.

An optional long-encode check uses a generated looping video, paces real ffmpeg, and verifies that the job is still running past 180 seconds before checking its completed 185-second output:

```bash
JARVIS_TEST_LONG_ENCODE=1 .venv/bin/python -m pytest tests/test_background_conversion.py::test_background_video_encode_survives_foreground_timeout -q -s
```

Portable tests generate audio and images and decode actual converted output. They exercise ordinary foreground conversion too, cancellation during real ffmpeg, lease loss, killed workers, output/input limits, and policy changes. Optional `JARVIS_TEST_VIDEO` / `JARVIS_TEST_IMAGE` paths enable representative-media tests using temporary copies and disposable outputs; no private media is committed. PDF conversion is not supported by this adapter.

Incoming callbacks pass the separate [Phase 3a local HTTP gate](TASK-CALLBACKS.md#isolated-acceptance-proof), covering middleware, body limits, authentication, durable inbox and one saved answer after another Web tool turn. A long-running Samantha binding or another provider is added only after its completion POST contract is packaged and verified for that deployment. The optional public relay remains future work as a separate deployable service; none of these integrations is required for local background execution.
