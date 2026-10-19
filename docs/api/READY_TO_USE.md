# Start using the proactive API

Jarvis's REST API accepts alerts from monitoring systems, scripts, and other
applications. It also provides reminder, query, workflow, memory, and media
endpoints. The background services handle reminder delivery, alert follow-ups,
URL recovery checks, and scheduled tasks.

This guide assumes Jarvis is installed and the selected mode is configured.
For initial setup, see the [Install Guide](../INSTALL_GUIDE.md).

## Start the API and services

Run these commands from the repository root. If the normal Jarvis stack is
already running, check its status before starting another instance. Start the
API in one terminal and leave that terminal running:

```bash
./bin/jarvis-api
# Use --local instead for local configuration
# ./bin/jarvis-api --local
```

Start the background services from a second terminal:

```bash
./bin/jarvis-services
# ./bin/jarvis-services --local
```

The API listens on port **8880** by default. The Web chat server is a separate
application on port **5001**. Starting the API alone does not start the reminder
scheduler or the other background daemons.

```bash
# In another terminal, check the running components
./bin/jarvis-api --status
./bin/jarvis-services --status
curl http://localhost:8880/api/health
```

Open [interactive API documentation](http://localhost:8880/docs) to inspect the
running server's request schemas and available endpoints. A dark version is
available at [Docs Dark](http://localhost:8880/docs/dark).

## Configure client access

Review [API security settings](../SECURITY_HARDENING.md) before connecting remote
clients. The API supports bearer-token authentication and access controls; add
the required authorization header when authentication applies to your client.
The localhost examples below use the default port. From another device, use the
server's reachable address and configured access method.

## Send an alert

This request creates a real alert and may speak it through the host's configured
TTS provider:

```bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Backup failed",
    "description": "The scheduled backup did not finish.",
    "severity": "high",
    "source": "backup_monitor"
  }'
```

Use a stable `source` name to identify the integration. The response includes an
`alert_id` for later inspection and acknowledgement. To see pending alerts:

```bash
curl 'http://localhost:8880/api/alerts?status=pending'
```

To acknowledge one, replace `ALERT_ID` with the returned identifier:

```bash
curl -X PUT http://localhost:8880/api/alerts/ALERT_ID/acknowledge
```

Alerts and reminders are also visible in the [Memory UI](../../jarvis-memory/README.md)
and the Web notification panel. Acknowledging an alert stops its pending
follow-ups; reaching the follow-up limit does not itself acknowledge the alert.

## Choose how an alert clears

- **Manual acknowledgement:** dismiss the alert through the API or UI.
- **URL recovery:** provide an `auto_resolve_url` for the self-healing daemon to
  check. A healthy response can resolve the alert automatically.
- **Integration-driven recovery:** the originating system can report recovery
  through the alert API.

A successful later scheduled task does not automatically clear every failure
alert from an earlier occurrence. Use the lifecycle appropriate to the source.
See [Alert scenarios](code-examples/ALERT_SCENARIOS.md) for integration examples.

## Select a mode

| Setting | Cloud | Local |
| --- | --- | --- |
| Launcher option | Default | `--local` |
| Configuration | `config/cloud.env` | `config/local.env` |
| Default memory and operational database | `data/jarvis_memory.db` | `data/jarvis_memory_local.db` |
| Host speech | Configured cloud-mode TTS | Configured local-mode TTS |

Mode selects configuration and data; the configured providers determine whether
a request uses external services. Local mode alone does not make every enabled
tool offline. Alerts, reminders, and scheduled tasks stay mode-specific; memory
sync is not automatic synchronization of those operational records.
See [dual database behavior](../DUAL_DATABASE_SYSTEM.md) and
[query mode selection](QUERY.md).

## Related guides

- [API reference](README.md): endpoint guides for queries, workflows, memory, and media.
- [Background services](../service/README.md): lifecycle, schedules, logging, and cleanup.
- [Proactive system architecture](../service/PROACTIVE_ASSISTANT_SYSTEM.md): how alerts and scheduled work fit together.
- [Manual API checks](TEST_API.md): requests against a running instance.
- [Testing guide](../TESTING.md): the isolated regression suite for contributors.
