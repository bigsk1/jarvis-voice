# OpenCode V2 permissions and workspace controls

Jarvis's OpenCode service supports unattended builds. It must allow the
operations needed to build workspace projects while constraining where those
operations can write. User intent, prompt instructions, and logs alone do not
enforce filesystem boundaries.

## Effective permissions

V2 uses ordered rules under `permissions`. For example:

```json
{
  "permissions": [
    {"action": "shell", "resource": "*", "effect": "allow"},
    {"action": "edit", "resource": "*", "effect": "allow"},
    {"action": "external_directory", "resource": "*", "effect": "deny"}
  ]
}
```

This is an illustrative policy, not a replacement for the tracked configuration
or workspace plugin. The last matching rule wins. Global and agent-specific
rules both matter. V2 also translates supported V1 `permission` settings, but
the tracked setup uses the native V2 shape.

- `allow` permits a matched action without an interactive prompt.
- `deny` rejects it.
- `ask` creates a pending approval request. Jarvis currently reports this as a
  blocker and interrupts the unattended session; it does not answer approvals.

Build mode does not bypass permissions. Plan mode denies ordinary edit tools,
but shell actions still need an appropriate policy. See the upstream
[permission reference](https://opencode.ai/v2/docs/permissions/) and
[agent modes](OPENCODE_AGENTS.md).

## Layers used by the native Jarvis service

| Layer | Purpose | Limit |
| --- | --- | --- |
| Session instructions and workspace `AGENTS.md` | Tell the agent where and how to work | Guidance; not an access-control boundary |
| V2 permission rules | Allow, ask, or deny matched tool actions | Depends on effective ordered rules and the tool's resource declaration |
| Workspace protection plugin | Validate supported edit paths against the workspace and protect the Jarvis checkout | A tool hook does not inspect every possible shell or JavaScript filesystem operation |
| Linux systemd filesystem restrictions | Restrict filesystem writes by OpenCode, shell commands, Code Mode, and child agents | Workspace, required OpenCode state/cache paths, and private temporary storage remain writable |
| Jarvis supervision | Detect blockers/failures, limit duration, propagate cancellation, report final results | Does not remove the service's network access or credentials |

Read access is broader than write access so OpenCode can inspect source and
installed dependencies. The Linux service is not a container or a complete
sandbox. Provider credentials supplied to the service may be available to
trusted plugin and child-process code. Use a dedicated service account or
stronger isolation when the workload requires a stricter boundary.

The writable runtime exceptions include `~/.local/share/opencode` and
`~/.local/state/opencode`. These contain shared session/credential databases and
state. Child shells, Code Mode, and
subprocesses have the same access to them as the server, so coding work can
read, modify, or delete the server's shared state. Project/session separation in
the OpenCode UI does not isolate these files. Private temporary storage is also
writable; network access and service credentials remain available.

OpenCode and common package caches are redirected into the workspace under
`.cache/`; Cargo and Go use `.toolchains/` for their user directories. These
paths remain writable by coding tasks. The old host `~/.cache/opencode` is no
longer a writable service exception. See
[package caches and toolchains](OPENCODE.md#package-caches-and-toolchains) for
the exact environment settings and host-managed Rust toolchain boundary.

The plugin applies to every session on its OpenCode server, including direct
terminal/web/API sessions. It does not restrict Jarvis's other tools or a
separate OpenCode process. Starting `opencode serve` manually does not reproduce
the tracked systemd filesystem restrictions.

The global `~/.config/opencode` directory is read-only inside the service. Use a
host editor or the setup scripts to change its config, provider, plugin, or
instruction files, then restart. Config-writing Web/API actions can fail;
session, credential, and saved-permission database storage remains writable.

## Setup and verification

Use [the maintained installation flow](OPENCODE.md), which installs the V2
plugin, prepares private credentials/configuration, and renders the service.
`./bin/update-opencode-service.sh` refreshes those artifacts after changes.
Keep matching `OPENCODE_SERVER_USERNAME` and `OPENCODE_SERVER_PASSWORD` values
in each Jarvis mode that calls the service.

Deterministic plugin tests check representative allowed/blocked file paths.
An authenticated `/api/info` response proves the server is reachable, not that
all write controls work. Validate the rendered unit and actual service
restrictions as well as plugin loading before relying on unattended coding.
Do not test protection by asking a live model to alter real system files.

See [plugin details](plugin/README.md) for the implementation, supported
operations, and test commands.
