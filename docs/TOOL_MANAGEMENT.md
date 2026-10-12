# Tool management

Jarvis combines local tool manifests, discovered MCP tools, and Tool RAG ranking.
Use manifests and profiles to choose the tool catalog, availability requirements
to hide integrations that are not configured, and request restrictions to control
what a particular surface can use. Tool RAG ranks only eligible tools; it does not
supply credentials or bypass these gates.

## Inspect and change tools

Run these commands from the checkout root:

```bash
./bin/manage-tools.py --mode cloud list
./bin/manage-tools.py --mode local list -v
./bin/manage-tools.py disable network_tools
./bin/manage-tools.py enable network_tools
./bin/manage-tools.py profile list
./bin/manage-tools.py --mode cloud profile show
./bin/manage-tools.py --mode cloud profile export > /tmp/tool-state.json
```

`enable` and `disable` edit the matching local manifest, including supported
`skills/auto-tools/` and `skills/personal/` folders. An active profile override
still wins over that manifest default. `enable-all` edits all local manifests;
inspect integrations before using it. MCP tool names are managed through server
configuration and profile overrides rather than local manifest edits.

After changing manifests, profiles, or integration settings, restart Jarvis and
sync the modes you use. Registry/profile configuration is loaded at construction;
editing a file does not update every existing process automatically.

Tool RAG sync uses the **production environment**, even when development tests
use the checkout's `.venv`:

```bash
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

The sync needs access to the configured embedding service. It deliberately
refuses the repo `.venv` to prevent fallback embeddings from entering Tool RAG.
Do not treat a blocked network connection as proof that the embedding host is
unhealthy. Run only the modes configured on your installation.

## Enabled, available, and selected

| Gate | Meaning |
| --- | --- |
| Manifest default | Local `enabled` value; omission means `true`. |
| Profile override | The active profile's Boolean value wins over the default. |
| Configuration availability | Required keys, enable flags, files, commands, or provider configuration exist in the active mode. |
| Tool dependencies | Every tool in `availability.requires_tools` is in the effective discovered catalog. |
| Request permissions | Global blocks, Web/request exclusions and any request allowlist also apply to dependencies. |
| Selection | Tool RAG, explicit hints and workflow routing choose from the remaining catalog. |

An enabled tool can still be unavailable. A profile setting of `true` cannot
supply a missing credential, discover a disabled MCP service, or override a
request restriction. Conversely, being available does not mean that a tool will
be selected for every relevant question.

The live registry is the execution catalog. Persisted Tool RAG rows provide
ranking and metadata; an old enabled database row cannot resurrect a tool that
is absent from the registry. Sync disables stale rows when an integration is
removed or becomes unavailable. Cloud and local checks use their own config
scope and profile settings.

Availability diagnostics contain requirement names and safe file paths, never
credential values. Availability metadata is not sent to the model and does not
change the Tool RAG embedding hash. Tool name, description and parameter schema
changes can require new embeddings.

## Local manifest schema

A minimal manifest is:

```json
{
  "enabled": true,
  "name": "example_lookup",
  "description": "Look up a record. Examples: 'find a record', 'show record details'.",
  "script": "example_lookup.py",
  "parameters": {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"]
  },
  "permissions": {
    "dangerous": false,
    "network": true,
    "filesystem": false,
    "bash": false,
    "auto_approve": true
  },
  "availability": {
    "enabled_env": "EXAMPLE_SERVICE_ENABLED",
    "all_of_env": ["EXAMPLE_API_KEY"],
    "setup_hint": "Enable the service and set its key in config/<mode>.env."
  }
}
```

Permissions describe execution behavior; they are separate from availability.
For a complete tool, also review child-process environment, timeout, output,
follow-up context, and any background adapter. See [tool authoring](../skills/README.md)
and [background tasks](BACKGROUND-TASKS.md).

### Availability fields

Omit `availability` entirely for tools with no hard requirements. When present,
all declared requirements must pass, except for the alternatives described below.

| Field | Requirement |
| --- | --- |
| `enabled_env` | One config-variable name whose value must be `true`, `1`, `yes`, or `on`, ignoring case and surrounding whitespace. Credentials alone do not enable a service. |
| `all_of_env` | Non-empty list of variable names; every value must be non-blank. |
| `any_of_env` | Non-empty list of variable names; at least one value must be non-blank. |
| `config_files` | Non-empty list of non-empty regular files. Relative paths resolve from the project root; absolute and `~` paths are supported. Contents are not validated by discovery. |
| `all_of_commands` | Non-empty list of executable names that must exist on `PATH`; discovery does not execute them. |
| `webhook_registry` | Non-empty list of entries in `config/webhook_registry.json`, each with a non-blank URL after environment substitution and without `enabled: false`. |
| `requires_tools` | Non-empty list of exact registered tool names; every dependency must be callable in the relevant catalog. |
| `provider_requirements` | Map of provider names to credential requirements. At least one provider must be configured. This does not authorize switching providers automatically. |
| `provider_setting` | Optional config key identifying the selected provider for diagnostics. |
| `provider_default` | Optional fallback provider name for those diagnostics. |
| `setup_hint` | Optional operator-facing setup text; keep it free of secrets and private host details. |

Malformed requirements and unknown field names fail closed for the affected
tool, including a typo alongside otherwise valid fields. The result has
`status: unavailable` and `<invalid availability metadata>` in its diagnostics.
Independent tools continue loading. Presence checks cannot prove that an API
key is valid or that a remote service will stay healthy; execution still needs
its own preflight and error handling.

### Hard tool dependencies: `requires_tools`

Use `requires_tools` when a tool cannot work without other registered tools.
For example, the command inbox needs Gmail search, raw message reads, and sending:

```json
{
  "availability": {
    "enabled_env": "GOOGLE_WORKSPACE_MCP_ENABLED",
    "all_of_env": ["GOOGLE_ACCOUNT", "GOOGLE_WORKSPACE_MCP_TOKEN"],
    "config_files": ["config/contacts.json"],
    "requires_tools": [
      "mcp_google_workspace_search_gmail_messages",
      "mcp_google_workspace_get_gmail_message_content",
      "mcp_google_workspace_send_gmail_message"
    ]
  }
}
```

This uses the same mechanism as other local tools. Workspace off, a missing
Gmail tool, a profile-disabled dependency, or a blocked dependency makes
`email_inbox` unavailable. The private `jarvis_email` policy inside contacts is
an additional runtime opt-in; discovery checks file presence, not its contents.
See the [email inbox guide](tools/email-inbox-tool/README.md).
Its published [request sequence](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-sequence.html)
and [data-flow chart](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-dataflow.html)
show how dependency checks, sender policy and restricted execution fit together.

Registry loading first checks configuration, discovers local/MCP candidates,
then resolves dependencies against the effective catalog. Dependency chains
are supported. A self-dependency or a closed dependency cycle cannot establish
availability and stays unavailable. MCP recovery reapplies dependency checks,
so a recovered service can restore its dependents without forcing tools on.

Request restrictions use the same dependency closure. If a request excludes
Gmail send, it also excludes the command inbox. Discovery and direct execution
both enforce this boundary. A request allowlist must include any dependencies
needed by the allowed tool; adding only the parent name is insufficient.
These checks restrict visibility and execution without removing tools from the
shared registry. A restricted nested request does not stop its dispatcher's
shared MCP clients.

`requires_tools` is different from top-level `prerequisite_tools`:

- `requires_tools` is a hard availability requirement.
- `prerequisite_tools` is a discovery hint for tools that help obtain inputs,
  such as finding an ID before looking up an entity. It does not enforce access
  or guarantee that the prerequisite is available.

### Static and Web diagnostics

`manage-tools.py list` and `profile export` do not start MCP connections. Without
a live catalog, a config-ready `requires_tools` check returns **unknown** with
`tool catalog required`; the list displays it as unverified. Missing config can
still produce a definite unavailable result. Unknown does not mean the server
is down and does not authorize execution.

Web dependency metadata inspects an existing registry for that mode, filtered
by profile and surface blocks. It does not open another MCP connection or use
cached Tool RAG rows as proof of discovery. Before a registry exists, dependency
availability is unknown and the dependent is not offered as enabled. Subsequent
metadata reads update this state after registry creation or recovery. This is
a discovery snapshot, not a continuous remote health probe.

## Profiles and MCP configuration

Profiles are JSON overlays in `skills/profiles/<name>.json`:

```json
{
  "description": "Keep normal tools, disable autonomous workflow selection.",
  "overrides": {
    "workflow": false,
    "ssh_remote": false
  }
}
```

Select the stem in the mode's environment file:

```dotenv
JARVIS_TOOL_PROFILE=my_profile
```

Omitted tools retain their manifest defaults. Unknown names do not create tools.
Copy a template from `skills/profiles/examples/`, edit the destination overlay,
restart services, and sync that mode. `profile export` is a diagnostic report,
not a ready-to-load profile file. See the [profile templates](../skills/profiles/examples/README.md).

MCP servers live in `config/mcp-servers.json`. Their enable flags and transport
configuration determine discovery; profiles can then disable individual
`mcp_<server>_<tool>` names. Enabling a local manifest does not start a disabled
MCP integration. See [MCP setup](mcp/MCP_QUICKSTART.md),
[remote transports](mcp/MCP_REMOTE_TRANSPORT.md), and the relevant integration's
own setup guide. Optional local tools use reviewed `child_environment` policies;
MCP services use their server configuration instead.

The optional manifest `proxy_policy` controls networking at runtime:
`inherit`, `off`, `prefer`, or fail-closed `require`. It is not an availability
requirement. See [network proxy configuration](NETWORK_PROXY.md).

## Discovery, hints, workflows, and background tasks

`tool_search` and `workflow` are promoted as discovery candidates only while
present in the effective registry and permitted for the request. A manifest,
profile, or request exclusion can disable either one normally.

Disabling the `workflow` meta-tool stops autonomous discovery/execution through
that tool. It does not disable explicit slash workflows or scheduled workflow
tasks. Those entry points still check component-tool availability and their
execution surface's restrictions.

Tool descriptions should include a few representative user phrases to help
semantic ranking. A selected tool hint expresses user intent; adding an
integration should not silently inject preference hints for generic requests.
Intentional attachment actions can have their own narrowly defined tool policy.
Intelligence insights can inform selection within the permitted catalog.

Selecting a tool for Web background execution is another layer, separate from
availability. Only reviewed adapters can be admitted, and admission validates
arguments and background constraints before creating a job. Provider-hosted
search tools are also separate from the local/MCP catalog. A restricted request
allowlist disables provider-hosted tools and explicit workflow routing so they
cannot bypass that boundary. See [background tasks](BACKGROUND-TASKS.md).

## Measure Tool RAG behavior

The total enabled catalog is not the number of schemas sent to the model.
Inspect the final shortlist before attributing context size or latency to a tool:

```dotenv
TOOL_RAG_TRACE_ENABLED=true
```

Traces are written to `logs/tool-rag/tool-rag-YYYY-MM-DD.jsonl`. Useful fields
include `final_tool_count`, `tool_schema_chars`, `tool_schema_est_tokens`,
`tool_schema_top`, `ranked_tools`, and `excluded_tools`. Compare representative
queries in the same mode/model. Character-based token estimates are approximate;
there is no fixed percentage saving from disabling a particular tool.

Execution logs in `logs/tools/` record calls under the `tool` key. For example:

```bash
jq -r '.tool' logs/tools/*.jsonl | sort | uniq -c | sort -rn
```

Treat logs as private: they may contain requests, file references and results.
See [Tool RAG strategy](TOOL_RAG_STRATEGY.md) and
[the tool calling system](TOOL_CALLING_SYSTEM.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Enabled but unavailable | Read `missing` and `setup_hint`; verify config in the selected mode, then restart/sync. |
| Dependent marked unverified | A static inspector has no live catalog. Check runtime discovery; do not bypass `requires_tools`. |
| Dependent missing despite credentials | Check its enable flag and every exact dependency name, MCP discovery, profile, global blocks, and Web/request restrictions. |
| Tool remains disabled after `enable` | Check the active profile; its override wins. |
| Old DB row still visible | Restart the relevant runtime and sync that mode. Persisted metadata is not execution authority. |
| Available but never chosen | Inspect Tool RAG traces, user phrases, description and final schema cap; availability does not force ranking. |
| Tool found but request denied | Check surface exclusions, the request allowlist and dependency closure; do not force-register it. |
| Workflow cannot run | Check each step against the execution catalog and surface, even when the workflow itself is enabled. |
| Configured service fails during execution | Availability is not a health monitor. Inspect bounded tool errors, service logs and runtime timeout/recovery behavior. |

For a new first-class tool, use [the authoring guide](../skills/README.md) and
its own `docs/tools/<tool>/README.md` for prerequisites, mode settings, examples,
outputs, and troubleshooting. Tool ideas belong in [TOOL_IDEAS.md](TOOL_IDEAS.md)
rather than this operational guide.
