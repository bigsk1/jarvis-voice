# Quiet notifications

`create_notification` records routine updates without creating an alert,
speaking on the Jarvis host, or enrolling in spoken alert follow-ups. Use it
for successful cron runs, selected workflow findings, and requested updates.
Keep `create_alert` for actionable problems. Existing alerts, reminders,
background-task forwarding, and the yt-dlp watcher retain their behavior.

## Shared entry points

The tool, REST endpoint, and ordinary Python callers use
`lib.notifications.NotificationStore`. Creation writes a local record and
delivery intent; the existing ntfy worker publishes and retries independently.
Web and model services need not be running for cron to record a notification.
No new service or package is required.

```bash
"${JARVIS_VENV:-$HOME/jarvis-venv}/bin/python" skills/create_notification.py \
  '{"title":"Report ready","message":"The weekly report is ready to review.","source":"weekly_report","channels":["ntfy"],"dedupe_key":"weekly-report:2026-W43"}'
```

| Field | Meaning |
| --- | --- |
| `title` | Required nonempty title, at most 200 characters. |
| `message` | Required nonempty text, at most 2,000 characters, intentionally published to requested channels. |
| `source` | Producer name, up to 80 characters; default `manual`. |
| `channels` | Default `["ntfy"]`; `[]` saves history only. Unknown channels are rejected. |
| `dedupe_key` | Optional stable occurrence identity, up to 200 characters. Reusing it with the same mode/source returns the original notice without resending. |
| `max_age_seconds` | Delivery freshness from 60 to 86,400 seconds; default 3,600, also capped by channel configuration. |

Use a release version, finding ID, or task run ID as the key. A permanent job
name would suppress later occurrences. Omitting the key creates a new notice
on every call. Delivery retries never rerun the source job.

Direct Python composition uses the same writer:

```python
from lib.config_loader import get_active_config_mode, get_project_root
from lib.notifications import NotificationStore

notice = NotificationStore(get_project_root(), get_active_config_mode()).create(
    title="Report ready",
    message="The weekly report is ready to review.",
    source="weekly_report",
    dedupe_key="weekly-report:2026-W43",
)
```

Tool arguments accept no server URLs, credentials, topics, or webhook
destinations. The tool works without ntfy configured; its restricted child
environment does not inherit provider credentials.

## Delivery and history

Tool output has `ok`, `speech`, and `data`. `ok: true` confirms local storage.
`data.id` identifies the record; `data.deliveries` tracks each channel separately:

- `pending`: queued, possibly waiting for a retry.
- `delivered`: ntfy returned a valid acceptance receipt; phone arrival is unverified.
- `failed`: a terminal error or retry limit stopped delivery.
- `suppressed`: delivery expired or its channel was disabled.
- `unavailable`: the channel was missing, disabled, or invalid at creation.
- `saved`: aggregate state for a history-only notice with no channels.

Unavailable notices never replay merely because a channel is enabled later.
Temporary network failures with valid enabled configuration leave deliveries
pending for bounded retries. Disabling the channel suppresses pending delivery
when the worker next observes the change. A dropped acknowledgment after server
acceptance can still cause a duplicate on retry; delivery is not exactly-once.

The existing `data/ntfy_notifications.db` gains tables for notices and
per-channel delivery state. Old cursors and receipts are preserved without
replay. Content is cleared after 90 days on a subsequent worker cycle, creation,
or history access. Minimal identity and receipt records remain so old dedupe
keys cannot resend. This retention applies to both modes in the shared database
and needs no cleanup cron. This store stays outside memory sync.

History is mode-scoped. One worker delivers explicitly requested notices from
either mode, preserving their origin. Automatic alert/reminder scans retain
their existing launcher-mode behavior.

## Web and REST

**Jarvis Web → Settings → Notifications** contains channel switches, ntfy
health/test controls, and paginated history. History includes standalone notices
and alert/reminder/background-task delivery receipts. Filter by source type,
channel, state, and mode. Old receipts show source references rather than
discarded message bodies; older send times can be unknown. Alert management
remains in its existing interface.

Channel switches change only known booleans in an existing private
`config/ntfy.json`, preserving credentials and other settings. Reads and switch
changes never publish; **Send test** does. Missing/invalid configuration needs
host setup first. Docker's default read-only config mount supports viewing;
edit the host JSON to change switches there.

REST exposes `POST /api/notifications` with the same tool fields and optional
`mode` (`cloud` or `local`); omission uses the API's active mode.
`GET /api/notifications` accepts `mode`, `source_type`, producer `source`,
`channel`, `state`, `limit` (1–100), and `offset`. Both follow existing API
authentication: external requests need a Bearer token when
`JARVIS_API_AUTH=true`; existing loopback exemptions remain. Web routes use
normal Web authentication. These operations neither create alerts nor call models.

## Workflows and cleanup

Run `/notification_test` deliberately to record the current UTC time and request
one notice. It makes no model calls, is excluded from autonomous workflow
discovery, and creates a fresh occurrence per run. Completion confirms storage;
check history and the phone separately for delivery.

Other workflows can add a conditional `create_notification` step after their
threshold checks. Use `required: false` and `on_fail: "continue"` when recording
failure should not invalidate completed work. An earlier required failure aborts
the pipeline, so a later notice step is not a general failure finalizer. Decision
scores and thresholds belong upstream; this feature invokes no decision model
and does not alter the GitHub radar or yt-dlp recipes.

Successful normal `bin/cleanup-all` runs record a notice with a unique run key.
The existing cron entry needs no change. `--no-notify` opts out for that run.
`--dry-run` creates neither success notices nor failure alerts. Cleanup failures
retain the existing failure alert; notification failures are logged without
changing cleanup success. An unavailable disk-usage summary logs a warning
without changing successful cleanup into a failure. Individual cleanup commands
do not notify automatically.

One cleanup run covers shared logs, generated images, Web conversations and
uploads, plus runtime audio from both Cloud and Local. Stash uses the selected
mode's configured root and retention settings; custom roots can differ between
modes. The notice is stored in that selected mode's history. Cron defaults to
Cloud when `JARVIS_MODE` is unset; select Cloud in the history filter to see that
notice while using a Local Web session. The History mode selector filters this
list without changing the application's mode or what the cleanup run deleted.
Creating this success notice and the automatic 90-day notification retention are
separate operations. Do not schedule duplicate full cleanup runs just to make
the same result appear in both histories.

## Setup and upgrades

Follow the [ntfy delivery guide](../../NTFY_NOTIFICATIONS.md). The new
`notifications` category defaults to enabled when ntfy itself is enabled, with
topic `jarvis-notifications` and freshness 3,600 seconds. Subscribe the phone to
this topic and grant the publisher account write access. Existing private JSON
without this section uses those defaults; `notifications.enabled: false`
disables this delivery source. Local history remains available.

Restart native services to load the worker, Web tab, and tool registry; refresh
the browser and sync Tool RAG for configured modes. Docker requires rebuilding
and recreating affected images, retaining existing config/data mounts. Schema
additions are automatic; no manual migration, extra env key, or new credential
type is needed. Discord adapters and automatic per-tool notification policies
remain future additions using this shared writer.
