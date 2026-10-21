# OpenCode V2 plugins in Jarvis

OpenCode V2 uses a new plugin API. A V1 plugin implementation cannot be made
compatible by renaming its directory or configuration entry. Jarvis ships a V2
workspace protection plugin at
`docs/opencode/plugin/00-workspace-protection.js`.

Use the maintained install/update scripts to install it alongside the native
service:

```bash
./bin/install-opencode-service.sh
# After tracked plugin, service, provider-key, or auth changes:
./bin/update-opencode-service.sh
```

The scripts prepare the config/environment, sync the tracked plugin, render the
systemd unit, and verify the running V2 service. See
[setup](OPENCODE.md#new-native-linux-installation) for the complete first-time
flow and [the plugin README](plugin/README.md) for implementation details.

## Scope

The plugin runs inside OpenCode and applies to every session on that server,
including terminal, Web, and direct API sessions. It does not modify Jarvis's
other tools. It validates supported edit paths against the configured coding
workspace and protects the Jarvis checkout; source reads are permitted.

A plugin hook alone cannot constrain arbitrary shell, Code Mode, or
child-process writes. Jarvis's native Linux service also uses systemd filesystem
write restrictions. See [permissions](OPENCODE_PERMISSIONS.md) for the layers
and their limits.

## V2 plugin management

V2 configuration uses `plugins`; preferred local discovery locations are
`.opencode/plugins/` and `~/.config/opencode/plugins/`. Legacy singular plugin
folders remain discoverable for compatibility. An explicit local-directory
plugin entry is also supported. Avoid installing two copies of the same
workspace guard.

The V2 CLI provides `opencode plugin list`, `opencode plugin check`, and
`opencode plugin update` for package-plugin management. A package update does
not refresh Jarvis's tracked local plugin; use Jarvis's update script for that.
Do not apply package-plugin updates indiscriminately to an unattended service.

For new plugin development, use the upstream
[V2 plugin guide](https://opencode.ai/v2/docs/plugins/) and
[build documentation](https://opencode.ai/v2/docs/build/plugins/).
The old plugin ideas and experiment reports in this directory are historical
V1 material and are not the current setup contract.
