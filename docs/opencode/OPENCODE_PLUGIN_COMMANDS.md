# OpenCode V2 plugin and service commands

Run from the Jarvis checkout. The maintained scripts use the selected mode env
and install the tracked local workspace plugin; package-plugin CLI commands do
not replace this step.

```bash
# Install or refresh the native service and tracked plugin
./bin/install-opencode-service.sh
./bin/update-opencode-service.sh

# Alternate env source
OPENCODE_ENV_FILE=config/local.env ./bin/update-opencode-service.sh

# Check running service and startup/plugin errors
sudo systemctl status opencode-jarvis.service
journalctl -u opencode-jarvis.service -n 50 --no-pager

# Check V2/auth connectivity without a provider call
./tests/integration/test-opencode-integration.sh --health cloud

# Deterministic client/tool tests
./tests/integration/test-opencode-integration.sh

# Review Jarvis logs or a known service session
./bin/opencode-logs --verbose
./bin/opencode-session <session_id>
```

An API listener or an entry in configuration does not by itself prove a plugin
loaded. Use the install/update script's runtime verification and the journal.
Do not print complete configuration or provider credentials as a diagnostic.

For package plugins, V2 provides:

```bash
opencode plugin list
opencode plugin list --builtin
opencode plugin check
```

These commands normally target OpenCode's own shared service. They may inspect
a different process from Jarvis's dedicated port-4096 systemd service. Use
`opencode --help` and an explicit `--server` where supported when working with
the Jarvis instance.

For the current file-operation guard and tests, see
[plugin/README.md](plugin/README.md). For complete setup, permissions, service
scope, and V1 migration, see [OPENCODE.md](OPENCODE.md).
