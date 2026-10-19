# Service architecture FAQ

This guide explains how the proactive services interact with the API, voice
interface, and scheduled work. See [Background services](README.md) for commands
and [Proactive system architecture](PROACTIVE_ASSISTANT_SYSTEM.md) for the data flow.

## Which processes need to run?

The REST API receives integration requests. Four core daemons handle alert
follow-ups, URL/service recovery checks, reminder delivery, and scheduled tasks.
The native launcher can also start the optional phone notification worker.
Native voice, Web chat, Canvas, and the other dashboards have their own processes.
Starting one interface does not imply every other component is running.

```bash
./bin/jarvis-api --status
./bin/jarvis-services --status
```

Use the normal stack launcher or the component launchers documented in the
[service guide](README.md), with a consistent cloud or local mode.

## Do background services call an LLM?

The follow-up daemon, reminder scheduler, and ordinary URL recovery checks work
from stored data and rules. Their notification delivery uses the configured TTS
provider rather than asking a chat model to decide each action.

The **scheduled task runner can call LLMs and tools**. Query tasks enter normal
Jarvis orchestration; workflow tasks execute their configured steps. The REST
API also exposes query and generation endpoints that can use providers. Budget
and permissions therefore depend on the operation being run, not simply on
whether it originated from a service.

## Can notifications incur provider costs?

Yes. Host speech can use a paid TTS provider, and scheduled tasks can use paid
models or external tools. Local services can avoid those provider charges when
all required components are local. No fixed monthly cost applies to every setup.

Review configured providers, task frequency, and the structured usage logs.
The follow-up daemon limits pending alerts to three follow-ups per alert, but
that limit is not a spending cap for scheduled workflows or other API requests.

## How are alert follow-ups timed?

The follow-up daemon uses this severity-based schedule:

| Severity | Wait before each successive follow-up |
| --- | --- |
| Critical or high | 15, 30, then 60 minutes |
| Medium | 30, 60, then 120 minutes |
| Low | 60, 180, then 360 minutes |

The wait is measured from the last follow-up, initial speech, or creation time
as applicable. At most three follow-ups are sent. Acknowledgement, cancellation,
or resolution stops pending follow-ups. Reaching the limit leaves the alert's
lifecycle state unchanged.

## Are reminders cron jobs?

Reminder delivery is a daemon loop that checks for due reminders every 60
seconds. A reminder can therefore be delivered shortly after its stored trigger
time rather than at the exact second. Recurring reminders also use the scheduler.

Cron is used separately for maintenance, such as the watchdog and cleanup, when
installed. See the [reminder reference](../api/REMINDER_SYSTEM.md) and
[service maintenance settings](README.md).

## What happens if one component stops?

Processes have separate lifecycles:

- If the API stops, new API/webhook requests cannot be received. Already running
  daemons and native voice do not automatically stop with it.
- If a daemon stops, its work pauses until recovery. Other components can remain
  available. For example, the API can store an alert while follow-up delivery is down.
- If native voice stops, API and browser entry points can remain available.

They still share resources such as databases, providers, disk, and host audio.
Separate processes do not guarantee that a provider or database outage has no
cross-component effect. A health response also does not prove every workflow
or speech provider is functioning.

## What restarts a crashed service?

In the native setup, the self-healing daemon monitors supported sibling daemons
and selected services. The optional five-minute cron watchdog restarts
self-healing when a stale PID file indicates an unexpected exit. An intentional
stop removes the PID files so the watchdog does not immediately undo it.

The API has its own lifecycle and is notify-only in sibling monitoring; do not
assume every failed service will be restarted automatically. Docker and systemd
deployments also depend on their configured supervisor. Details and supported
processes are listed in the [service guide](README.md#watchdog-cron).

## Can two notifications speak at once?

Each notification can start a separate TTS process, but the native speech scripts
share a playback lock when `flock` is available. This serializes playback rather
than relying on the audio device to mix competing announcements. Audio generation,
lock waits, playback, and their failures remain separate stages.

Browser playback has its own controls and does not use this host playback lock.
See [speech formatting and delivery](../AUTO_MODE_EXPLAINED.md).

## Does local mode mean everything is offline?

Mode chooses configuration and data. Offline operation also requires local chat,
STT/TTS, embeddings, and a tool profile that disables network-dependent tools.
A local-mode scheduled workflow can still call a network tool if it is enabled.

Cloud and local operational records are separate. Memory sync does not copy
alerts, reminders, or scheduled tasks. See [Dual databases](../DUAL_DATABASE_SYSTEM.md).

## How do I investigate a missing or repeated notification?

Check the saved item and its lifecycle in the Memory UI, then inspect service
logs for the source and time range. Distinguish an unsaved request, a stored
pending alert, a speech failure, and a later follow-up. A successful subsequent
workflow run does not automatically acknowledge all older task-failure alerts.

[Service logging](SERVICE_LOGGING.md) documents log paths and query examples.
The Web [Logs Viewer](../logging/README.md#web-ui-log-viewer) provides a browser interface.

## How can contributors check changes?

Run the deterministic core suite from the repository root:

```bash
./bin/test-suite
```

The [testing guide](../TESTING.md) explains focused checks, local fixture
permissions, saved reports, and separate live/provider tests. API examples against
a running instance can create real alerts, reminders, speech, or provider work;
they are not substitutes for the isolated regression suite.
