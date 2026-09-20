# Browser Use

This page covers the **local** Docker/Chromium integration. The separate
[Browser Use Cloud](BROWSER-USE-CLOUD.md) tool uses Browser Use's hosted V4 API
and does not need Docker or Jarvis task callbacks.

`browser_use` is an opt-in AI research tool using the upstream
[Browser Use](https://github.com/browser-use/browser-use) agent and headless
Chromium in Docker. It follows the originating Jarvis conversation's selected
provider and model. Local mode stays local; cloud mode keeps its selected cloud
provider. There is no second model picker or API-key configuration.

The integration is **Web text chat → background task → HTTP callback → late
answer**. The tool uses the normal manifest, availability/profile/ENV/UI controls,
Tool RAG, progress events and Stash, with `http_callback_v1` as its only execution
adapter. Settings → Tools remains the saved background allowlist; enabling tool
discovery alone does not authorize execution.

The manifest is enabled by default so Tool RAG can index it. Request-time discovery
uses the existing blocked-tool mechanism: Browser Use is excluded unless the caller
is authorized Web text chat, the saved background switch and tool choice are on,
a compatible worker/coordinator is ready, and its trusted callback source is enabled,
tested and has usable credentials/key storage. The callback receiver must also be
on and the source must accept both success and failure events. Semantic Tool RAG,
exact `tool_search` lookups and the model's schemas share this filter. Turning a
setting on/off takes effect on subsequent requests without resyncing Tool RAG.
Automatic exclusions never edit Settings' saved block list; manual blocks still win.

`browser_use` declares `execution.background.required: true`. With background
requirements unmet it is hidden from model selection. A stale or forced call returns
an immediate error without starting work. Voice, Talk, Firefox Companion, query API, CLI and nested
workflows cannot run it. The public skill script also refuses direct execution;
only the callback service launches its private job entrypoint with isolated Python
startup (`-I`). There is no
foreground fallback or caller-supplied flag that grants background permission.
Admission rechecks readiness after selection, and the worker checks service health
before submitting. Request-time discovery makes one short authenticated health
check for the Web turn, then shares that result across routing and Tool RAG. A
selected tool hidden by a failed eligibility check logs its AdmissionDenied
reason. No discovery snapshot guarantees that a service remains up until admission.

## Deployment

The Compose service pins the official `browseruse/browseruse:0.13.10` image by
manifest digest. It includes the agent, Chromium and their Python dependencies.
No Browser Use or Playwright package is added to Jarvis's Python environment.
The evaluated AMD64 image is approximately 2.16 GB installed (680 MB compressed).
This reuses the upstream agent's reasoning, DOM extraction and action handling;
it is not a smaller browser installation.

For the normal native setup, start Jarvis as usual, then open **Settings → Tools →
Background tasks** and click **Set up and enable** on Browser Use. That one action:

1. checks Docker and downloads the pinned Browser Use image when needed;
2. creates and verifies the private callback source and credential;
3. enables incoming callbacks and the saved Browser Use background permission; and
4. starts the managed `jarvis-browser-use` tmux helper.

The first download is large and can take several minutes. Setup returns HTTP 202
immediately; Settings polls the setup state while a dedicated Web background thread
downloads the image and finishes provisioning. Another setup click joins the same
attempt. An interrupted Web process leaves an interrupted state that can be retried;
the image pull is never replayed as a browser research job. Docker failures appear
in Settings without holding a chat request for the 15-minute pull budget.
After this one-time setup, the normal `bin/start`, `bin/start --ui-only`, and
`bin/start --no-api` groups start the configured helper along with the task worker.
`bin/start --stop` stops both. Setup restarts a stale Browser Use tmux helper. It also
starts the task worker or replaces an idle older worker that does not advertise the
callback adapter. It refuses to restart a worker while work is running or has a
reserved Needs-attention slot; reconcile that work and retry setup. Repeating setup
leaves a healthy Browser Use helper alone, including while research is running.
Stopping the managed helper gives active research time to archive its partial
evidence and send a failed callback. If that graceful stop cannot finish within
45 seconds and research is still active, the tmux session stays in place and the
stop command reports an error rather than killing the callback path.

The Integrations tab is advanced administration for custom callback sources and
delivery history. Normal Browser Use setup does not require editing a source,
creating credentials, or testing the receiver there.

The equivalent CLI commands remain available for troubleshooting and automated
installations:

```bash
source "${JARVIS_VENV:-$HOME/jarvis-venv}/bin/activate"
docker compose -f docker-compose.browser.yml pull
python bin/jarvis-browser-use check
python bin/jarvis-browser-use setup --callback-base http://127.0.0.1:8880
python bin/jarvis-browser-use start --tmux
```

The API port must match your installation. The low-level `setup` command only
creates the source and owner-only `data/secrets/browser-use.json`; the Web action
also enables, verifies, selects, and starts it. The callback URL must reach the
**API**, not just the Web UI. Restart API when applying migration 8 for the first
time; API does not migrate the task store itself.

The browser callback service runs in tmux for the current native workflow. It is
not installed as systemd. Its default
submission address is `http://127.0.0.1:8790/submit`. The existing task worker must
also be running. Each admitted callback job starts its own disposable container using
`docker compose run --rm`; there is no always-on browser or exposed CDP port.
This first deployment requires the native Jarvis host to have Docker access;
mounting a Docker socket into a containerized Jarvis is not supplied or required.
The ordinary Jarvis Docker Compose stack does not run this managed helper.
Settings → Tools marks Browser Use native-only there and disables setup. Web,
worker and API containers have separate loopback namespaces. The optional MCP
socket overlay does not make Browser Use operational there. See the
[Docker deployment boundary](docker/README.md#background-tasks-and-task-callbacks).

Attach to the helper for its live, high-level service and callback messages:

```bash
tmux attach -t jarvis-browser-use
```

Detach with `Ctrl-b`, then `d`. A quiet pane while no job is running is normal. The
durable audit described below is the better source for completed activity.

### Updating the pinned image

The tag and manifest digest in `docker-compose.browser.yml` are intentionally pinned;
Jarvis never follows `latest`. To upgrade, choose and review an upstream release,
replace both the version tag and digest, pull that exact reference, run the Browser
Use tests plus one controlled live research task, then restart the helper. Restart
refuses while a Browser Use research job is active, so let current work finish first:

```bash
docker compose -f docker-compose.browser.yml pull browser
.venv/bin/python -m pytest tests/test_browser_use.py tests/test_browser_use_journey.py -q
./bin/jarvis-browser-use restart --tmux
```

`docker image inspect` can confirm that the local image matches the reference in the
Compose file. Commit the Compose change with its test evidence so an upstream image
change can never alter an installation silently.

## Isolation, model and network policy

The agent and Chromium run as the image's non-root user with Chromium's sandbox
explicitly enabled, a read-only root filesystem, tmpfs scratch, dropped
capabilities and CPU/memory/process limits. Only the adapter entrypoint is mounted
read-only. No repository, Stash, provider credentials, personal profile, Docker
socket or callback secrets are mounted. Telemetry and Browser Use cloud sync are
disabled. The image's provider wrappers are not used.

The container has `network_mode: none`. Bounded JSON messages over stdin/stdout
connect it to three Jarvis capabilities:

- Model calls use the existing `create_configured_provider` factory and tool-schema
  conversions, preserving runtime selection and provider authentication. The first
  version uses DOM text, with vision disabled so text-only local models work.
- Page fetches resolve and validate every destination on the host, then connect
  to one validated IP while retaining the URL hostname for HTTP Host, TLS SNI
  and certificate verification. The manifest declares `"proxy_policy": "inherit"`;
  the existing ordered proxy chain, fallback and `off`/`prefer`/`require` semantics
  apply per request. Proxy requests also target that validated IP, so proxy-side
  DNS cannot rebind the destination. A host-loopback proxy works too. Redirects
  return to Chromium and the next URL is checked again. Browser service workers,
  WebSockets or unhandled targets cannot bypass this bridge to reach the LAN.
- Evidence checkpoints and the final report are written by the host through
  `open_space` and `StashFile.save_text` before returning a result.

Only GET/HEAD requests are forwarded. Form submissions, uploads, video streaming,
login, shell, arbitrary model-supplied JavaScript and file-access actions are not
exposed. Browser Use retains navigation, clicking, scrolling, text search and
extraction. Read-only GET is not a guarantee that every website is free of side
effects. Browser downloads are disabled; evidence is a bounded Markdown report
and the DOM text observed by the model, not a complete website mirror.

Responses are capped at 3 MiB per resource, with a 400-request / approximately
96 MiB task budget and bounded concurrency. This transport uses Jarvis HTTP TLS
rather than Chromium's native network stack. Sites requiring browser TLS
fingerprinting, WebSockets, POST-based APIs, cross-origin iframe interaction or
login may not work. These limits are explicit; there is no silent unrestricted
browser fallback. Public hostnames must resolve only to public IPs; the destination
is pinned to a validated address for each request. A deployment-only
`BROWSER_USE_ALLOWED_HOSTS` list can permit explicit private IP literals for
local tests. Allowlisting a hostname does not permit DNS rebinding to a private
address; model arguments cannot change the list.

The container reports a normal Linux Chrome user agent whose major version is
derived from its installed Chromium build; Chrome client hints and navigation
headers cross the bounded bridge. Authorization and arbitrary headers remain
blocked. This removes an avoidable `HeadlessChrome` signal, but it is not a stealth
or CAPTCHA-bypass feature: the origin still sees Python Requests TLS. Changing the
manifest to `"proxy_policy": "off"` bypasses Jarvis's configured `LOCAL_PROXY`
chain for new jobs, but it cannot bypass a host/VPN network route and it does not
change that TLS fingerprint. Keep `inherit` unless a deployment has evidence that
its configured proxy is the source of a site-specific block.

The seccomp profile derives from Playwright v1.63.0's Apache-2.0-licensed
[Docker profile](https://github.com/microsoft/playwright/blob/v1.63.0/utils/docker/seccomp_profile.json),
with `chroot` permitted for Chromium's user-namespace sandbox under `cap_drop: ALL`.
This profile is independent of the browser-agent library. No `SYS_ADMIN`,
privileged mode, host networking or host AppArmor changes are required.

## Results and recovery

Each observed page is checkpointed into the same Stash research file. A terminal run
saves its final sourced report before producing a job result. The callback carries
the bounded report plus a reviewed `browser_research` presentation containing its
Stash reference, visited source URLs, provider and model. This presentation is also
kept when the agent returns useful partial evidence but cannot satisfy the full goal;
the task remains failed and Web labels the card **Partial browser research**. Startup
failures before a Stash archive exists keep the ordinary error presentation.
The browser observation ends at least 45 seconds before the original job deadline,
including when a job waited in the queue, to leave room for verified stop and
callback delivery. A job with too little time left returns a preflight failure.
Verified stops, timeouts and child errors keep a partial card when an archive
exists. Unverified process-group or container termination stays uncertain; it
cannot safely produce a terminal callback. The receiver accepts the reviewed shape only for a source-bound
`browser_use` job and never downloads callback-supplied URLs. Web renders the report
directly as Markdown instead of asking a second LLM to shorten it. Normal Stash
retention applies; pin research you want to keep.

Captured DOM evidence is untrusted page text. The Browser Research Stash viewer
renders it literally in bounded, scrollable evidence blocks rather than interpreting
its HTML-like element notation as Markdown or HTML. This keeps archived source text
readable in dark mode and prevents a page snapshot from changing the viewer layout.

## Audit trail

Browser Use writes daily owner-only JSONL files to
`logs/browser-use/browser-use-YYYY-MM-DD.jsonl`. They record service/job lifecycle,
model-call boundaries, callback delivery, each allowed or rejected browser request,
HTTP status/byte counts and observed page steps. Destinations retain scheme, host,
port and a bounded path so unexpected sites are visible; URL credentials, query
strings and fragments are removed. Prompts, page contents, reports, cookies, headers,
provider responses and secrets are never logged. Request records include the
reviewed `proxy_policy`, so an operator can distinguish proxied-policy and direct
runs without exposing proxy addresses. Isolated `--db` runs write beside
that database under `logs/browser-use/` rather than into installation logs.

For a quick audit:

```bash
tail -f "logs/browser-use/browser-use-$(date -u +%F).jsonl" | jq .
jq 'select(.event == "request_rejected" or .level != "INFO")' logs/browser-use/*.jsonl
```

The JSONL format is suitable for a later Grafana Alloy/Loki pipeline without changing
the Browser Use execution path. `bin/cleanup-logs` includes the installation's
`logs/browser-use/` directory under its normal 60-day default (or `--days N`)
when invoked. This change does not schedule cleanup or prune
`data/browser-use.db`. Logs from isolated `--db` runs outside the installation's
logs directory need their own
retention policy.

The browser service commits submissions before acknowledgement, using the attempt
ID as its idempotency key. Conflicting work under that identity is rejected.
Completion state and the outgoing callback commit together. Progress/completion
POSTs retry the same event ID with fresh authentication timestamps and bounded
backoff for transport failures, 408/425/429 and 5xx. Definitive 4xx rejection
is retained with its status and no automatic retry. After fixing the
receiver/source/credential, run `bin/jarvis-browser-use retry-delivery --attempt-id ATTEMPT_ID`
before the original deadline (the attempt ID is in the helper audit). This
requeues only parked events; it never reruns the browser. A 409 for a conflicting
event ID needs operator reconciliation instead: replaying the same conflicting
bytes cannot succeed.

Known Docker/image preflight failures return a failed callback promptly with setup
instructions. No browser or model call has started, so applying that callback
releases the running slot instead of waiting for the deadline/Needs attention.
Started work becomes uncertain after a service crash, never queued again.
A helper or Docker stop with verified process-group and container termination
delivers a failed partial result; only unverified termination stays uncertain.
Jarvis's original deadline fences an attempt still awaiting callback. **Cancel** on
one Browser Use task card or in Manage tasks saves a request for that exact attempt.
The helper checks it at most once a second, stops only that job's container, and
sends `task.cancelled` after verified termination. Cancellation is card-only, with
no new assistant reply; any saved partial research remains available through the
task card and Details. A queued helper job acknowledges cancellation without
starting Chrome. An unverified stop remains uncertain and needs reconciliation.
The helper can remove this attempt's container even when the Python child has
already stopped; an independent container watchdog and stdin-EOF check add a
second stop path. Container stop does not prove an already-submitted model
request stopped, but the read-only browser task cannot continue after its
container is gone.

The service runs at most two job children. Jobs have a 900-second budget
including queue time, with up to 30 agent steps. Service rows in
`data/browser-use.db` persist for audit/idempotency; automatic service-history
pruning and reconciliation of service-local uncertain rows are not implemented.
Uncertain rows remain as no-replay evidence but do not occupy the 32-item
queued/running execution limit. Partial Stash research survives failures even
when no completion callback can safely be delivered.

The agent tolerates up to five transient model/action failures within that budget.
It is instructed to finish with the best supported partial report when sites are
blocked instead of abandoning the run. A terminal audit event records bounded step
and error counts without logging model output or page contents. Direct publisher or
topic pages are preferred as starting URLs; Google Search and Google News commonly
return automation challenges before research begins.

Credential expiry/revocation blocks admission at the worker and result ingestion
at API. Rotate through Settings, update the private service credential and restart
the browser service and worker. Never delete the task database to rotate keys or
recover work.

## Follow up on saved research

After a local Browser Use job finishes, reply in the same Jarvis Web
conversation. Jarvis can send its background job ID as `continue_job_id`
instead of another starting URL. The worker checks conversation ownership,
then uses the prior report and last available source URL (or original starting
URL) to start a new isolated browser
job. This carries research context across runs, but the earlier Docker
container, live tab, cookies, and page interaction state have already been
destroyed. Local Browser Use remains read-only and cannot continue a signed-in
Gmail action. Wait for the earlier job to finish before submitting a follow-up.
The prior job result must still be retained in the background task store.

## Verification

```bash
.venv/bin/python -m pytest tests/test_browser_use.py tests/test_browser_review_gates.py tests/test_browser_use_journey.py tests/test_task_callback_journey.py -q
```

Normal tests use temporary stores and scripted providers. The optional live
journey uses the real Docker agent, configured cloud model and public Example
Domain page, with Stash, credentials and conversations isolated under pytest temp:

```bash
JARVIS_LIVE_BROWSER_TEST=1 .venv/bin/python -m pytest tests/test_browser_use_journey.py -q
```

Live evaluation also exercises the selected local and cloud models on controlled
multi-page content containing a random JavaScript-rendered value. A separate
public Example Domain → IANA run verifies the inherited proxy path. These tests
are separate from manually exercising the deployed Web UI.
