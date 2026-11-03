# Jarvis Workflows

Jarvis Workflows is an optional visual editor for Jarvis's existing deterministic
workflow recipes. It has its own HTTP server on port **5005**, so editing and
supervised workflow runs do not share Jarvis Web's listener or request workers.
It uses the existing Python environment, Flask, classic browser scripts, and SVG;
there is no new package, frontend build step, external workflow engine, or
provider account to configure for editing.

## Start and stop

Native launches use the existing production environment
`${JARVIS_VENV:-$HOME/jarvis-venv}`:

```bash
./bin/start workflows
# Or explicitly select config/local.env:
./bin/start --local workflows
./bin/start --list
./bin/start --stop-workflows
```

Default full-stack, UI-only, and no-API starts leave the builder off. Full stop
also stops it when present. The TUI has explicit Workflow Builder start, stop,
and log commands under Workflows. Inspect native output with
`tmux attach -t jarvis-workflows`.

For a foreground process with custom binding or port, activate the production
environment and run:

```bash
./bin/jarvis-workflows cloud --host 0.0.0.0 --port 5005
```

The default bind is `0.0.0.0`, matching the existing standalone UIs. Open
`http://localhost:5005` on the server, or `http://<reachable-host>:5005` from
another device. Only the selected startup mode's existing configuration file is
needed; a local-only checkout does not need a cloud placeholder.

Docker uses the existing image and data mounts:

```bash
docker compose --profile workflows up -d --build jarvis-workflows
docker compose logs -f jarvis-workflows
docker compose stop jarvis-workflows
```

The builder stays off with the default and `extras` profiles. Root `.env` can
set `JARVIS_WORKFLOWS_PORT` to change its published host port; container port
5005 stays fixed. Retain any existing `-f` overlay arguments. The MCP overlay
keeps the builder on the base Docker tool profile without a Docker socket.
The optional Ollama overlay supplies its daemon URL without making editor
startup wait for model initialization. Tools that require the Web container's
host integration are unavailable in the builder container.

Code changes need an image rebuild/recreation. Native environment updates do
not change existing images. The launcher and UI use the same cloud/local mode
rules as the other standalone servers. Docker Desktop follows the project's
existing experimental [macOS and Windows support](docker/MAC-WINDOWS.md).

## Edit, publish, and run

The library distinguishes shared and personal files, effective overrides,
disabled recipes, duplicate IDs, and validation errors. Opening a tracked recipe
does not write to it. Create a draft, or customize a recipe and publish either a
new personal copy or an explicitly reviewed personal override. Publication and
updates write only beneath `data/workflows/personal/`.

The editor shows an ordered sequence of tool steps. Select a step to edit its
schema-backed parameters, output variable, conditions, loop, retry, and
validation settings. Reorder steps, undo/redo, or use the complete JSON view for
fields without a dedicated form. Existing unknown JSON fields survive editing;
runtime semantics remain defined by the
[workflow format contract](../data/workflows/README.md). This is an ordered
pipeline editor, not a general parallel graph scheduler.

Each configuration field has a **?** help control with a format explanation and
an example. Hover the field heading, focus the help control with the keyboard,
or tap it to keep the example open. Escape closes it. Examples work on plain
HTTP and need no provider connection. Custom variables are optional: leave
`{}` to use built-in values such as `${topic}`. Variable names appear without
`${...}` in the variables JSON; parameters use `${name}` to refer to them.

Dropping a step on another card inserts it immediately before that card;
insertion points also accept steps, including the end of the lane. Arrow
buttons move a step one position. Neither action renumbers its step label.
Workflow-level `retry` and `partial_speech`, and step-level `llm_hints`, are
preserved as unused fields rather than presented as active controls. Use the
step loop-candidate limit and workflow validation policy for the supported
failure limits.

Draft saves and publication use revision/source checks. If another tab or an
external editor changes the source, reload and review it before overwriting.
Malformed recipes remain inspectable with diagnostics; publication and execution
require valid runtime structure. Deleting a personal override exposes any
remaining shared definition with that ID.

Local tool schemas are available without provider calls. **Refresh MCP tools**
explicitly discovers configured servers and saves a mode-specific catalog.
Cached MCP schemas are labeled as cached; current availability is checked again
before a run. The selected mode's profile, configuration, Web blocked-tools
list, and workflow restrictions determine which tools can run.

**Run live** prepares the selected published recipe and query for review, then
starts a supervised child process against that immutable snapshot. Preparation
and validation do not execute component tools. Query previews describe known
inputs and leave runtime-dependent values unresolved. Actual runs can contact
providers, consume credits, save files, or perform the recipe's requested actions.

Unless authorized by the recipe's published trust choice, confirmation-required
calls pause after their final arguments are prepared,
including generated content and each loop item. Approvals apply to that exact
call; a changed recipe, mode, or invocation needs a new decision. Denial, expiry,
or cancellation stops the run rather than retrying the action. Reload the page
to recover run status, progress, and pending approvals without submitting again.

Only one builder run is active at a time. Use **Stop run** to request termination.
Stopping a local process does not establish that a remote API action was undone;
inspect retained provider recovery IDs before repeating uncertain work. Runs
interrupted by service/process restart are reported as interrupted, not resumed
or automatically replayed. Saved results and history stay available after reload.
Successful runs through an earlier selected step are labeled **partial
completion**, including in history; running through the final step is a normal
full run. Worker startup failures retain bounded diagnostic information, such
as exception type, missing module, and code location, in the run and server
logs. Arbitrary child output, credentials, and complete prompts are not copied
into these diagnostics.

## Published runtime policy

Every recipe published by this UI receives the reserved
`builder_policy_version: 1` field. The server preserves it through raw JSON
editing, import, copying, and export. Upgraded Jarvis workflow execution checks
this policy through the shared executor, including slash commands, direct API,
the workflow tool, CLI, and scheduled workflows. Existing manually maintained
recipes without the field retain their trusted-filesystem behavior. Unknown or
malformed policy versions fail closed.

Managed recipes cannot use arbitrary environment variables to turn credentials
into workflow data. Only the reviewed nonsecret environment settings accepted by
the shared policy are permitted; integration credentials remain tool-owned.
The default names are `JARVIS_DEFAULT_LOCATION`, `JARVIS_DEFAULT_POSTAL_CODE`,
`JARVIS_MODE`, `UPCOMING_MOVIE_RADAR_EMAIL_TO`, and
`UPCOMING_TV_RADAR_EMAIL_TO`. An operator can add reviewed nonsecret names through
`WORKFLOW_BUILDER_ALLOWED_ENV_KEYS` in the selected mode configuration; the
browser cannot change that allowlist.
General code/agent delegation and recursive workflow steps are excluded from
managed recipes. This policy uses the existing tools' permissions and reviewed
boundaries; it does not add an operating-system sandbox around every tool.

Current Web/mode tool blocks are reread at admission and dispatch. Before
publication, the review lists the steps that require confirmation for each
configured mode, including optional or conditional steps. Without recipe trust,
these recipes require the builder's approval channel; unattended slash, API,
and scheduled runs reject them before any component tools run.

To retain unattended use, explicitly select **Trust this recipe for unattended
runs** in the publish review. This authorizes the named tools for that exact
published recipe, including arguments resolved later from queries or model
output. It applies to builder runs as well; the initial live-run effects review
still applies. Unknown or cached tool metadata is identified in the review so
the named tools can be accepted explicitly. Global tool blocks, selected-mode
availability, environment restrictions, and excluded tool categories remain
enforced. No global tool permission is changed.

The server writes a reserved `builder_unattended_approval` containing the recipe
hash and authorized tool names. Changes to the recipe invalidate the grant;
publishing again requires a fresh choice. Imports and raw draft edits cannot
create a grant. A stale preview or changed permission list requires another
review. Other eligible managed recipes use existing entrypoints normally.
Run mode selects tool/provider configuration and does not duplicate the recipe
or merge cloud/local data. The builder does not create schedules in v1.

**Upgrade all workflow-executing services before publishing managed recipes.**
Older running Jarvis processes do not understand the marker. Restart the API,
Web, scheduler/background services, and any long-lived CLI/voice process after
the code upgrade, preserving the deployment's selected mode. Stopping only the
builder does not update those callers. Direct operator filesystem changes remain
the original local trust boundary.

## Storage, login, and navigation

Drafts, cached catalogs, prepared runs, bounded event/history records, and pending
approvals use a separate `data/workflow_builder.db` SQLite store. Its versioned
schema is initialized automatically and rejects unknown versions; it does not
migrate memory, Intelligence, or background-task databases. Published JSON is
the runtime source of truth. Other workflow callers do not need the builder
database or server to run compatible published recipes.

History is bounded to the latest 500 runs and 30 days; each run keeps at most
5,000 progress events. Drafts remain separate from published files.

Back up this database with SQLite-consistent tooling and back up personal recipe
JSON separately. Both are private runtime data excluded from Git and images.
The existing Docker `./data:/app/data` mount retains them across recreation;
container UID/GID must be able to write there. A fresh clone has no private
recipes or history and requires no builder-specific configuration file.

Authentication follows the existing shared WebUI pattern. `WEBUI_PASSWORD`
remains optional, existing tokens and the shared signing secret are reused, and
no new login requirement or network-authentication policy is introduced. A
same-host shared cookie works across UI ports; different hostnames require
their own browser login.

The optional Workflows launch icon appears on desktop only when configured or
reachable. It stays hidden at mobile widths, including after resizing, so it
does not consume another slot in the Web UI's mobile navigation.

The optional Workflows navigation link appears when its browser origin is
explicitly configured, or an HTTP same-host status probe identifies a running
`jarvis-workflows` service. It stays hidden when the optional server is absent.
For HTTPS or a custom published port, add a `workflows` origin to the matching
hostname in ignored `config/ui_urls.json`, using
[the example](../config/ui_urls.example.json). Reload the page after changes.
An origin is a scheme, hostname, and optional port, without a path or credentials.
For optional Tailscale Serve, map an available HTTPS port such as 8447 to backend
5005 and set that browser-reachable HTTPS origin; see
[Tailscale HTTPS](TAILSCALE_HTTPS.md).

The public `/api/status` reports the service name, version, and startup mode.
Other API routes follow the existing UI login setting. The new UI does not
change FastAPI authentication, other UIs, browser extensions, or native audio.
