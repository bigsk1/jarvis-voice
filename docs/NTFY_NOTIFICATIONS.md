# Optional phone notifications with ntfy

Jarvis can forward selected saved events to an authenticated HTTPS ntfy server.
The independently supervised worker is `services/ntfy_notifications.py`. It
reads source databases without modifying them and owns
`data/ntfy_notifications.db`. It makes no LLM calls and does not delay event
creation, speech, Web responses, or background-task completion.

## Configuration

Copy `config/ntfy.json.example` to `config/ntfy.json`, set `enabled` to `true`,
and supply your HTTPS server origin and a **write-only ntfy publishing token**.
Run `chmod 600 config/ntfy.json`. The real configuration is excluded from Git
and Docker builds; the example is safe to distribute. Do not use a Coolify
management token or an ntfy administrator token in Jarvis.

Defaults send new high/critical alerts to `jarvis-alerts` and triggered reminders
to `jarvis-reminders`. Background-task success/failure notifications are
**opt-in**: set `background_tasks.enabled` to `true` and subscribe to
`jarvis-tasks`. This covers background jobs, not every scheduled-task result.
Scheduled workflows that create eligible alerts are covered by alert delivery.

Each category has an independent `enabled`, `topic`, and `max_age_seconds`.
`alerts.severities` controls severity selection. Alerts expire after 30 minutes,
reminder occurrences and task notifications after one hour by default. Pending
delivery stops when an alert is acknowledged/resolved, a reminder is canceled or
acknowledged, or a task is canceled/archived/expired. A recurring reminder's next
occurrence can send another message. Speech success is not required for phone
delivery; reminders are observed after the scheduler records their trigger.

The worker sends titles only by default. `include_descriptions: true` adds alert
and reminder descriptions, limited to 2,000 characters. Task results, prompts,
conversation contents, and management credentials are never forwarded. Consider
lock-screen previews when deciding what notification text to enable.

On the first successful scan of each category and mode, current records form a
**silent baseline**. Already-existing alerts and already-triggered reminders
are not replayed. Later events are delivered once according to local receipts.
Disabling a category discards its pending deliveries and baseline; enabling it
again starts a fresh baseline. Keep it disabled for at least one polling cycle
so the running worker observes the change. Missing/disabled configuration keeps
the worker idle. Invalid configuration fails closed and logs the error type.

Delivery retries use bounded exponential backoff, up to five attempts, and only
while the event is fresh and still eligible. Authentication failures and
redirects stop that delivery immediately. A source database failure delays that
source's deliveries without blocking the others. Local receipts prevent routine
duplicates across restarts. A connection failure after ntfy accepted a message
can still cause a duplicate on retry; ntfy publishing does not provide an
exactly-once transaction with the local database. Notifications already delivered
to the phone are not recalled when their source resolves.

## Running the worker

Web **Settings → Profile → System Info** shows an ntfy card below Tailscale.
It reports private configuration readiness, HTTPS server health, and the worker's
shared heartbeat. Checks run when Profile opens or **Refresh** is clicked;
opening the card never sends a notification. Health results are cached for 15
seconds. An online server does not by itself verify publishing credentials or
phone delivery.

**Send test** publishes one labeled notification to the first enabled category's
topic (alerts, then reminders, then background tasks). It works independently of
the event worker to help diagnose delivery. The API requires the normal Web
authentication, uses the configured publisher token without returning it to the
browser, and limits tests to one attempt per 30 seconds. A receipt means ntfy
accepted the test; confirm its arrival on the phone to verify push delivery.

The heartbeat is `logs/ntfy_notifications.status.json`, written privately and
atomically by the worker that owns the delivery lock. Stale/missing status is
shown as unverified rather than presumed healthy. Restart the worker after
upgrading to pick up heartbeat reporting; Docker Web reads the shared file
without requiring a Docker socket or host process access.

The native `bin/jarvis-services` launcher starts/stops/reports the worker alongside
the existing daemons, and self-healing can restart it. Docker's `jarvis-services`
container starts it with `docker/services.sh`; that container's existing restart
policy handles daemon exits. Existing running services need a restart to pick up
the additional daemon. No new Python package or database migration is needed.

For a focused one-cycle check, use the repo environment:

```bash
JARVIS_MODE=cloud .venv/bin/python services/ntfy_notifications.py --once
```

Logs are in `logs/ntfy_notifications.log`. A single shared file lock prevents
native/Docker or different-mode workers from publishing concurrently. The worker
waits when another daemon owns that lock, without scanning sources or publishing.
It logs contention once, retries every 15 seconds, and takes over when the owner
stops. SIGTERM/SIGINT ends the wait cleanly. Lock contention does not terminate
Docker's services container or its sibling daemons. The `--once` check still
returns an error immediately when another worker holds the lock.

The worker observes the launcher's active cloud/local mode and reloads notification settings
each cycle. Changing mode requires the normal service restart. Its state and
lock live in the existing mounted `data/` directory; source databases are
`jarvis_memory.db`, `jarvis_memory_local.db`, and `background_tasks.db`. Normal
source database retention/deletion causes pending deliveries to be suppressed or
expire. Retain the worker database across restarts to preserve delivery receipts.
Receipts retain identifiers and status; completed payload text is discarded.

Docker already mounts `config/` read-only. Ensure the container runtime user can
read your private config and write `data/`; do not loosen the secret file to
world-readable permissions to resolve an ownership mismatch.

## Secure self-hosting and iPhone setup

Use HTTPS, persistent cache/auth storage, `auth-default-access: deny-all`,
disabled public signup, and native ntfy login. Give Jarvis write-only permission
to the selected topics and a separate phone account read-only permission. Do not
add a second proxy Basic Auth header requirement: it conflicts with native app
authentication. Protect the topic APIs; the public login frontend and internal
health check do not grant access to messages.

In the official ntfy iPhone app, add your HTTPS server and reader account, then
subscribe to the enabled topics. Allow iOS notifications and check Focus and
notification-preview settings. Subscribe to a separate test topic and verify a
message arrives while the app is backgrounded or the phone is locked.

Self-hosted **instant iOS delivery requires**
`upstream-base-url: https://ntfy.sh`. The relay sends a generic wake-up containing
a message identifier and a hash of the topic URL; the app fetches the actual
message from your server. Without this relay, background delivery can be delayed
for hours. See the [official iOS configuration](https://docs.ntfy.sh/config/#ios-instant-notifications)
and [access-control documentation](https://docs.ntfy.sh/config/#access-control).

This is authenticated, encrypted **transport**, not end-to-end encrypted message
content. The server stores readable messages in its cache, and any TLS-terminating
proxy can access content. Use short cache retention, scoped credentials, and
minimal text. Standard ntfy does not make an E2EE guarantee.

The deployed image may use `binwiederhier/ntfy:latest`. To install upstream
security releases, pull/redeploy that image through Coolify. A mutable tag does
not update running containers automatically. Preserve the volume and review
upstream release notes when updating. Stopping the service is reversible;
deleting its volume loses cached messages and authentication state.
