# Jarvis's OpenCode V2 workspace plugin

`00-workspace-protection.js` runs inside an OpenCode 2.x server. The native
install/update scripts copy it to
`~/.config/opencode/plugins/00-workspace-protection.js` and verify that the
running server loaded it. It applies to all sessions on that server, including
sessions opened directly from a terminal, browser, or API client. It does not
restrict Jarvis's other tools or unrelated OpenCode processes.

## What the plugin enforces

The guard validates supported edit/write/patch operations against
`JARVIS_WORKSPACE_ROOT` (default `~/jarvis-workspace`). It resolves paths and
existing symlinks before allowing edits, rejects writes outside the workspace,
and protects the Jarvis checkout. Source reads are permitted, including reads
of the Jarvis source.

Temporary files belong in the workspace's `temp/` directory. The service sets
its temporary-directory variables accordingly. A prompt or `AGENTS.md` file
provides guidance; the plugin is the tool-level write check.

A hook cannot inspect every write performed by arbitrary shell commands,
JavaScript Code Mode, custom tools, or subprocesses. The tracked Linux service
therefore also applies `ProtectSystem=strict`, `ProtectHome=read-only`, and
explicit `ReadWritePaths` for the workspace and required OpenCode state/cache
locations, with private temporary storage. The global config directory stays
read-only; edit config/plugin files from the host and restart the service.
A manually started server does not inherit those systemd controls.
See [permissions](../OPENCODE_PERMISSIONS.md) for the complete scope and limits.

OpenCode's shared runtime storage under `~/.local/share/opencode` and
`~/.local/state/opencode` remains writable by child
shells, Code Mode, and subprocesses. They can read or change session/credential
databases and other server state there. The guard provides no separate
per-session filesystem boundary for that shared storage.

OpenCode and package caches live under the workspace's `.cache/`; Cargo/Go user
directories live under `.toolchains/`. The old `~/.cache/opencode` path is no
longer a writable service exception. See
[package caches and toolchains](../OPENCODE.md#package-caches-and-toolchains).

## V2 implementation

The plugin exports a default object with a stable `id` and `setup(ctx)` and
registers the V2 tool-execution hook. It has no npm package dependency. This is
the same definition shape produced by V2's `Plugin.define`; V1's named async
plugin factory and `tool.execute.before` return-map API are obsolete.

Do not copy V1 plugin code into a V2 service. The installer moves the matching
legacy singular-directory workspace plugin out of discovery as a
`.js.v1-backup`, leaving other plugins for deliberate migration. Avoid adding
a second explicit config entry pointing to another copy of the same guard.

## Install and verify

```bash
# From the Jarvis checkout, with the V2 binary installed
./bin/install-opencode-service.sh

# Refresh tracked plugin, service config, keys, and authentication
./bin/update-opencode-service.sh

# Select a different source env explicitly
./bin/update-opencode-service.sh config/local.env

# Review startup/plugin failures
journalctl -u opencode-jarvis.service -n 50 --no-pager

# Deterministic integration tests; no provider call
./tests/integration/test-opencode-integration.sh

# Read-only configured V2/auth connectivity
./tests/integration/test-opencode-integration.sh --health cloud
```

The install/update scripts check the actual running V2 service and plugin,
rather than treating a config entry or a healthy HTTP listener as proof of
plugin loading. Review the effective systemd unit when validating filesystem
restrictions. Keep adversarial path tests deterministic and use disposable
files; do not ask a live model to alter real system files to test the guard.

Fresh installations seed global instructions from
[`config/opencode.instructions.md.template`](../../../config/opencode.instructions.md.template)
only when `~/.config/opencode/AGENTS.md` is absent. Existing global instructions
remain unchanged.

For a new plugin, follow the upstream
[V2 plugin API](https://opencode.ai/v2/docs/build/plugins) and
[V1 plugin migration guide](https://opencode.ai/v2/docs/build/plugins/migrate-v1).
The old plugin ideas/test reports elsewhere in this directory are historical
V1 material, not current safety evidence.
