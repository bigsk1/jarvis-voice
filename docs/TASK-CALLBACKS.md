# Task callbacks

For the plain-English overview of all three ways a background job can finish,
see [How background work finishes](BACKGROUND-TASKS.md#how-background-work-finishes).

Phase 3a adds authenticated completion callbacks for explicitly bound services.
Jarvis saves each accepted event to a durable inbox, the task worker applies it to
the matching execution attempt, and Web delivers the existing task card and late
answer. A service can respond after the submitting worker exits; no polling child
or long-lived chat turn is required.
The authenticated completion summary is the late answer itself. Web renders it
as a safe Markdown report card without asking a second model to condense it;
the callback result remains in conversation history for later inspection.

**Incoming callbacks default off.** [Browser use](BROWSER-USE.md) is the first opt-in
production binding; it requires explicit local service provisioning and runs only
through authorized Web text chat background admission. It has no foreground mode.
The existing conversion and media bindings keep their current runners. Adding a
source in Settings does not authorize it to run tools or create conversations.
An optional owner-installed personal callback binding can use the same adapter;
no remote tool or bridge is included in a public clone. Third-party signature
formats, remote cancellation, and the public relay remain separate work.
`/api/alerts` and outgoing webhooks are unchanged.

## Setup and controls

Restart Web, API, and the task worker together after updating. Task-store migration
8 preserves existing jobs and preferences and adds the inbox and credential tables.
Older processes cannot use the newer schema; do not mix worker versions. Install
the updated dependencies using the normal project workflow (`cryptography==49.0.0`
is now a direct dependency; other packages were not upgraded).

In **Settings → Integrations → Task callbacks**:

1. Initialize credential storage explicitly. Nothing generates a key at import or
   ordinary service startup.
2. Add a named source with its Jarvis **API** receiver base URL and local service
   submission URL. The generic Integrations form requires a literal loopback
   submit IP; it does not accept remote hosts or another Docker container's
   service name. Trusted deployment code can separately pin one exact HTTPS
   submit URL for a reviewed remote binding. No remote tool binding ships here.
3. Create a bearer or Jarvis HMAC credential. Copy the one-time secret into the
   sending service's private configuration. It never belongs in a prompt or tool
   argument. Subsequent reads show metadata only.
4. Enable the source and incoming callbacks, then select **Test receiver**. This
   sends an inert authenticated event over HTTP and checks that this installation
   saved it. It cannot run a tool. Changing URLs or accepted events requires a new
   test before new jobs can be admitted.
5. A reviewed tool binding, worker adapter, and the usual **Settings → Tools**
   allowlist are still required for actual tasks. None is enabled by default.

Local HTTP URLs must use a literal loopback IP, such as `http://127.0.0.1:8880`.
Otherwise the receiver URL must use HTTPS. URLs cannot contain credentials, query
parameters or fragments. The sending service must be able to reach that URL.
The API and Web are different listeners: a Tailscale URL that serves only Web does
not automatically expose `/api/task-callbacks/…`. Configure the route to the API
deliberately, then verify it with the setup test. No public listener or tunnel is
created by this feature.

### Optional private tool binding

An operator can install a Web-only callback tool under `skills/personal/` and
register it in the ignored, owner-only
`data/secrets/private-callback-bindings.json`. The separate file is required:
the tool manifest alone cannot select a source, enable the callback adapter, or
send to a remote host. It must be a regular `0600` file owned by the Jarvis
process user. Each entry pins the personal manifest and script SHA-256, the
source ID, exact HTTPS submit and receiver URLs, a same-host health URL, and the
service's submit bearer token. The model never supplies those values. A changed
file hash, disabled tool/profile, blocked prerequisite, changed source URL, or
failed health check denies new work; the worker rechecks before submission.

```json
{
  "version": 1,
  "bindings": [{
    "tool": "my_private_task",
    "source_id": "32_lowercase_hex_characters_here",
    "submit_url": "https://private-bridge.example/submit",
    "callback_base": "https://private-api.example",
    "health_url": "https://private-bridge.example/health",
    "submit_token": "replace-with-a-long-private-bearer-token",
    "manifest_sha256": "64_lowercase_hex_characters_for_the_reviewed_manifest_here",
    "script_sha256": "64_lowercase_hex_characters_for_the_reviewed_script_here"
  }]
}
```

`requires_tool` may optionally name a companion tool whose profile or block
setting should also disable this binding. The private tool must declare
`execution.background.required: true`, adapter `http_callback_v1`, and a reviewed
1–86400 second timeout. Its script should reject ordinary foreground execution.
Provision and test the source through trusted deployment code before setting its
ID here; the generic Integrations form intentionally cannot create a remote
submit destination. After installation, sync Tool RAG in the modes used, restart
Web and the task worker, then enable the tool in Settings → Tools. The callback
receiver and source remain separate switches in Settings → Integrations. Public
clones have no private binding file and gain no remote callback tools.

Operator requests stay on the Web origin and reuse mandatory configured Web auth,
explicit bearer tokens, and the allowed-Origin guard. Cookie-only, query-token and
cross-origin requests cannot administer sources. Authenticated CLI requests may omit
Origin. If HTTPS terminates at a proxy, configure the existing
`JARVIS_WEB_BACKGROUND_ALLOWED_ORIGINS` for the exact Web origin. Forwarded headers
do not authorize callers. At an untrusted proxy boundary, strip caller-supplied
forwarding headers and configure trusted proxy addresses in the server deployment.
Callback authentication is mandatory even over loopback or a trusted tunnel.

| Control | New admission / receipt | Previously accepted events |
| --- | --- | --- |
| Background admission off | No new jobs | Continue draining |
| Callback receiver off | No new callback-dependent jobs; new receipt gets HTTP 503 | Continue draining; authenticated duplicates get 200 |
| Source paused | No new source jobs; new receipt gets HTTP 403 | Held; revalidated after re-enabling; authenticated duplicates get 200 |
| Credential revoked | No new authenticated receipt with that credential | Held for explicit disposition |
| Source revoked | Permanently disabled; credentials revoked | Held; cannot reactivate this source |

The UI shows outstanding callback jobs, credential expiry/last use, and paginated
delivery verification/processing status. Every delivery displays its event and job
identity; expandable verification details include attempt, credential ID and payload
digest. Discard confirmation names the event and job. Revoked or expired evidence is never
silently released: discard it explicitly, or have the service send a new event ID
with a valid credential. Job reconciliation remains in **Manage tasks**, with
evidence that remote work has stopped. Receiver/source controls never prove that.

## Self-hosted protocol

`LocalCallbackRunner` is a trusted-code adapter with ID `http_callback_v1`. Its
binding maps a reviewed tool to a source ID and argument schema. Web stamps that
mapping into the job's authorization; incoming JSON and manifest metadata cannot
choose the mapping. The runner validates arguments, prebinds job/attempt/fence and
a random callback capability, then sends exactly one POST to the configured
submission URL. Ordinary sources use loopback; a reviewed deployment binding
may use an exact HTTPS URL that the runner checks again before sending:

```json
{
  "job_id": "jarvis-job-id",
  "attempt_id": "jarvis-attempt-id",
  "idempotency_key": "jarvis-attempt-id",
  "callback_url": "http://127.0.0.1:8880/api/task-callbacks/SOURCE_ID/events",
  "callback_capability": "per-attempt-secret",
  "arguments": {}
}
```

The service responds with HTTP 200 or 202 and `{"remote_id":"service-task-id"}`.
It must durably deduplicate submission by the idempotency key and retain the
callback context. Jarvis does not automatically resubmit if the receipt is lost.
Source credentials are provisioned separately, never included in this submission.
Redirects and ambient HTTP proxies are disabled; the response is bounded to 64 KiB
and a short observation budget. A lost or malformed receipt after binding leaves
the attempt open for its authenticated callback, without resubmission or a new
fence. An HTTP 4xx refusal other than an ambiguous 408 means no service work was accepted;
Jarvis commits a failed result and releases the execution slot. If no callback
ever arrives after an uncertain receipt, the original deadline still fences it.

POST events to `/api/task-callbacks/{source_id}/events` on the API:

```json
{
  "schema_version": 1,
  "event_id": "unique-service-event-id",
  "job_id": "jarvis-job-id",
  "attempt_id": "jarvis-attempt-id",
  "type": "task.completed",
  "result": {"summary": "The requested work finished.", "artifacts": []}
}
```

Every task event needs `Content-Type: application/json`, `X-Jarvis-Timestamp`
(decimal Unix seconds, within 5 minutes), and `X-Jarvis-Task-Capability` from the
submission. Additionally use **one** configured source credential:

- Bearer: `Authorization: Bearer CREDENTIAL_ID.SECRET`.
- Jarvis HMAC: `X-Jarvis-Key-Id: CREDENTIAL_ID` and `X-Jarvis-Signature: HEX_DIGEST`.
  The lowercase SHA-256 HMAC is computed with the UTF-8 secret over
  `timestamp + "." + source_id + "." + exact_raw_body_bytes`. Sign the transmitted
  bytes, not a parsed/reformatted JSON object. This is Jarvis's self-hosted protocol,
  not a claimed implementation of any third-party provider's signature scheme.

For a source-bound Browser Use job, a valid optional `presentation` adds the
research card. Invalid presentation metadata is discarded while a valid terminal
`summary` still completes the job; event identity continues to cover the original
submitted content. Presentation metadata on other tool bindings cannot create a
Browser Use card.

`task.progress` replaces `result` with `{"phase":"Rendering","percent":40}`;
percent is optional and phase is at most 256 characters. `task.failed` is a confirmed
terminal failure, not an observation timeout. `task.cancelled` is applied only for
an already requested cancellation; otherwise it is held. The reviewed Browser Use
binding supports per-job cancellation through its local helper, which verifies that
the exact container stopped before acknowledging it. Other callback bindings have
no running Cancel control by default. A valid cancellation acknowledgment updates
the card with suppressed delivery, matching local cancellation;
it does not schedule an assistant follow-up.

Phase 3a accepts **text results only**, up to 32,000 characters. `artifacts` must be
absent or empty. URLs, caller-selected stash references, tool names, conversation
IDs, provider settings, repeated JSON keys and undeclared fields are rejected.
No artifact is fetched or inline HTML rendered by the receiver.

## Delivery, limits and failure behavior

- HTTP 202 means durable inbox acceptance, not completed chat delivery. Identical
  event ID/content retries return 200; changed content under that ID returns 409.
  This acknowledgment survives receiver/source pauses and event-permission changes,
  without changing the inbox disposition or accepting new work. Retries still need
  a current source credential, timestamp/signature and the matching attempt capability;
  revoked or expired credentials return 401, even for a committed event.
  Fresh event IDs cannot produce a second terminal result or outbox entry.
- The source, credential, capability, job, attempt and execution fence must match.
  A callback can arrive before the submission receipt. Worker loss after handoff
  does not trigger replay or end callback observation; the job deadline still applies.
- The worker drains up to 100 events per loop using short SQLite transactions.
  Inbox disposition, terminal result and pending outbox commit together. With the
  worker offline, HTTP receipt remains durable; with Web offline, the result awaits
  continuation. Expired, disposed or reconciled attempts record late evidence and
  cannot reopen a conversation or produce another answer.
- A namespace-scoped outer ASGI boundary limits the actual streamed body to 1 MiB
  before request logging. Missing/dishonest Content-Length cannot bypass it.
  Compressed bodies, repeated auth headers and query parameters are rejected.
  Body receipt times out after 10 seconds.
- Pre-authentication limits are 120 requests per peer and 600 per minute for each
  loopback/remote ingress class **per API process**, with no loopback exemption.
  Direct remote peers cannot exhaust the managed loopback helper's budget;
  traffic forwarded by a local reverse proxy shares that loopback bucket.
  Authenticated new-event limits
  are persisted per source (default 60/minute, configurable 1–600). Durable duplicates
  do not consume that source allowance. General API/alert rate buckets are separate.
  A trusted proxy may collapse peers into one pre-auth bucket; source limits still apply.
- Pending/held inbox capacity is 10,000 events. Rate limits return 429 and
  `Retry-After`; unavailable storage/full inbox returns retryable 503. A sender must
  retry transport failures/429/503 with backoff and the same event ID/content,
  refreshing the timestamp/signature. Invalid credentials or schemas require a fix.
- Progress applies at most once per two seconds per attempt. Delivery history and
  metadata-only events in `logs/background-tasks/` aid diagnosis. Payloads, query
  strings, capabilities and secrets are excluded from API request logs. Existing
  proxy access logs need their own redaction; never put credentials in URLs.
- Inbox records currently remain for audit/deduplication; task-result retention
  does not purge them. Pending capacity and input/rate limits bound active work,
  but total audit history grows over time. A separate retention policy is future
  work and must preserve event identities and held evidence.

## Key lifecycle and recovery

Bearer secrets are stored only as SHA-256 verifiers of generated high-entropy
tokens. HMAC secrets use AES-256-GCM with fresh 12-byte nonces and authenticated
source/credential/version identity, following the pinned
[cryptography AESGCM contract](https://cryptography.io/en/49.0.0/hazmat/primitives/aead/).

The default versioned keyring is `data/secrets/task-integrations.key`; override it
with `JARVIS_TASK_INTEGRATIONS_KEY` consistently for Web, API and worker. This is a
service process environment setting, not a per-turn `config_scope` or Web override:
all modes sharing the database must use the same keyring. It must be
an owner-only regular file owned by the process user. Keep it separate from database
exports and back it up separately. Web needs write access for bootstrap/rotation;
API and worker need read access. Existing Compose data mounts share the default
path, but **the loopback adapter proof is native**, not a cross-container deployment.
Do not run simultaneous tmux and systemd workers; normal supervision is unchanged.

Local operator commands (using the normal runtime environment):

```bash
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-integrations init-key
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-integrations status
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" bin/jarvis-task-integrations rotate-key
```

`--db /absolute/path/tasks.db` and `--key /absolute/path/keyring` support isolated
operations. They do not configure running services. Missing keys are never
regenerated while credentials exist. Restore the matching key and database backup;
do not delete a key to fix an authentication error. Key rotation persists old and
new versions before rewriting/verifying ciphertext and retires old keys only after
the database commit. Interrupted rotation retains enough keys to retry safely.
Take backups while credential writes/rotation are quiescent so the pair is coherent.

Credential rotation is separate from encryption-key rotation. It shows a new secret
once and shortens the old credential to a bounded overlap (UI: 5 minutes; API:
0–60 minutes). Ordinary credentials default to 90-day expiry. Setup probes use
short-lived, test-only credentials and revoke them immediately after the test.

## Isolated acceptance proof

```bash
.venv/bin/python -m pytest tests/test_task_callbacks.py tests/test_task_callback_http.py tests/test_task_callback_journey.py tests/test_task_integration_controls.py tests/test_task_integration_ui.py tests/test_private_callback_bindings.py -q
```

All state, logs, credentials and conversations are temporary. The journey starts
`tests/fixtures/task_callback_service.py` as a separate process plus an ephemeral
localhost API server using the real auth/logging/rate/body middleware classes.
It exercises Web admission and receipt settlement, another foreground tool, one
authenticated completion plus its duplicate, and exactly one saved late answer.
Model decisions are scripted. This isolated receiver proof does not exercise the
production Browser Use binding, a live provider, real service configuration, or
installation data. The separate Browser Use tests cover that binding. The fixture
requires permission for local sockets.

The HTTP tests also verify middleware order on the actual API application. This
matters because [Starlette middleware order](https://starlette.dev/middleware/)
determines whether the streaming limit runs before body-buffering middleware.
