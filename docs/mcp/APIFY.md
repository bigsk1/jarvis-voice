# Apify: discover Actors and run them through one gateway

Jarvis discovers Apify-maintained Actors and explicitly trusted community
Actors, then uses the hosted [Apify MCP server](https://docs.apify.com/mcp) to
inspect inputs, outputs, and pricing. Policy-aware search uses the Apify Store
API behind the existing `mcp_apify_search-actors` tool name. Two Jarvis tools
handle execution and results for eligible, ordinary, limited-permission Actors:
`apify_run_actor` and `apify_read_result`. Each Actor supplies its own input
schema; adding another Actor does not require another tool, frontend adapter,
or Tool RAG entry.

Apify runs the Actors on its platform. Jarvis connects over HTTPS using the
selected mode's API token. This integration needs no local Apify server, Node
runtime, Docker container, new service, or additional database. Optional
background observation uses the existing Jarvis task worker and task store;
native run checkpoints reuse progress records without a schema migration.

## Enable the integration

Apify is opt-in. The public cloud/local env templates default to
`APIFY_MCP_ENABLED=false`; a token alone does not enable discovery or execution.
Set the following in each mode that should use Apify: `config/cloud.env`,
`config/local.env`, or both. Retain an existing `APIFY_TOKEN` instead of replacing
it with the placeholder below.

```dotenv
APIFY_MCP_ENABLED=true
APIFY_TOKEN=your_apify_api_token
APIFY_MAX_CHARGE_USD=1
APIFY_RUN_TIMEOUT_SECONDS=1800
APIFY_POLL_SECONDS=30
APIFY_MAX_MEMORY_MB=2048
APIFY_RESULT_PAGE_SIZE=20
APIFY_ALLOWED_ACTORS=
```

Get a token from [Apify Console](https://console.apify.com/account/integrations).
The token remains in private configuration. Jarvis places it in the explicit
bearer authorization header for Apify, rather than in tool arguments or URLs.
Local mode still makes external requests when this integration is enabled;
it does not reuse cloud mode's token.

The tracked `apify` entry in `config/mcp-servers.json` selects only
`search-actors` and `fetch-actor-details`. Jarvis also enforces that same tool
allowlist. Search is handled by Jarvis's policy-aware Store search; Actor details
still come from hosted MCP. Keep this selection: loading upstream execution
tools would provide another submission path outside Jarvis's run limits and
saved-run handling.
There is no need to load every Actor into the MCP session or the local registry.

After enabling, sync the selected mode's Tool RAG with the production Jarvis
environment:

```bash
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
# Run the local sync instead, or as well, only when local mode is configured.
```

Use the configured `JARVIS_VENV` when it differs from `~/jarvis-venv`.
`sync-tools.py` intentionally refuses the repository `.venv` and contacts the
configured embedding host. Restart the running Web, API, voice, and worker
processes that should load the change. Check the selected profile and Web's
blocked-tool settings if a tool remains unavailable.

Existing custom profiles are overlays and do not automatically gain new entries
from the tracked examples. If a mode enables Apify while using an older offline
profile copy, merge these entries into that profile's `overrides` object to
exclude discovery, execution, and reads, then restart and sync that mode:

```json
{
  "mcp_apify_search-actors": false,
  "mcp_apify_fetch-actor-details": false,
  "apify_run_actor": false,
  "apify_read_result": false
}
```

The tracked offline examples already include these entries. A profile's name
does not itself block external tools.

Docker installations use the same mounted mode configuration. Rebuild and
recreate existing Jarvis images after pulling this code; no Apify container or
Docker-socket access is needed. Follow the [Docker guide](../docker/README.md)
for tool sync and the optional `extras` or `background-tasks` worker profile.

## Tools and the normal request flow

| Tool | Purpose |
|---|---|
| `mcp_apify_search-actors` | Find relevant Apify-maintained Actors and configured trusted community exceptions. |
| `mcp_apify_fetch-actor-details` | Inspect the chosen Actor's schema, README, and pricing. |
| `apify_run_actor` | Validate input and start one bounded run by Actor ID or `owner/name`. |
| `apify_read_result` | Read an existing run's status, dataset page, or key-value record. |

For example, ask Jarvis to find an Actor for a source, inspect its requirements,
and then run the selected Actor. Input fields belong to that Actor's schema.
Jarvis's `actor` and `input` arguments stay the same across the catalog.

## Actor eligibility and trusted community exceptions

Apify-maintained Actors are eligible by default. This means the native Actor
owner username is `apify`, not a display badge or a claim in its description.
Jarvis checks this ownership metadata again when preparing a run. A community
Actor becomes eligible when its exact native Actor ID or `owner/name` appears in
the selected mode's `APIFY_ALLOWED_ACTORS` setting. Add an exception only for a
community Actor you personally trust.

This setting is additive. An empty value permits only Apify-maintained Actors.
Entries add trusted community Actors and keep all official Actors eligible.
For example, an existing value of
`APIFY_ALLOWED_ACTORS=apify/website-content-crawler` still leaves other official
Actors available. This replaces the earlier exclusive allowlist behavior;
the setting no longer restricts the eligible catalog to the listed entries.

Ratings, review counts, and usage are advisory signals for selecting an Actor.
There is no hard rating, review-count, or usage threshold. Low or missing values
do not automatically reject an official or explicitly trusted Actor.
Whitelisting grants publisher/quality eligibility; it never bypasses limited
permissions, cost, memory, runtime, build, or input-schema validation.

Search applies the official-publisher filter in the Store API and considers
relevant trusted exceptions. The public inputs remain `keywords`, `limit`
(1–10), and `offset`. It does not register a tool for each Actor. The hosted
MCP search cannot apply this publisher filter, so Jarvis uses the Store API for
search while retaining hosted MCP for `fetch-actor-details`.

Matching trusted exceptions appear first, followed by official Store results.
Official results use Apify's search; trusted exceptions match all query words
against their title, name, description, and publisher. Keep keywords focused.
Exception metadata reads share the search call's time budget. An incomplete or
failed exception lookup marks the result partial, with no combined total or
next-page offset; a later nonzero offset cannot return a reliable merged page.
Configured trusted Actors remain available for direct details lookup and run
preparation even when discovery is partial.

Both foreground submission and the optional Web background worker enforce this
same eligibility policy before starting a run. Configure exceptions through the
existing env setting; no separate policy file or approval screen is required.

The gateway rejects lookup metadata that does not match the requested native
Actor ID or exact `owner/name`, even when the returned Actor would otherwise
be eligible. It then resolves the Actor's successful default build, validates
the input against that build's original object schema, and pins its build number for
submission. It requires limited permissions and rejects standby/MCP-server
Actors, invalid or unavailable schemas, inputs over 60 KiB, and community Actors
without a trusted exception. These cases fail before a paid start when detected
during preparation.

Submission deliberately uses the native
[Run Actor API](https://docs.apify.com/api/v2/actors-runs-post). This lets one
shared gateway send the pinned build, timeout, memory ceiling,
`maxTotalChargeUsd`, `forcePermissionLevel=LIMITED_PERMISSIONS`,
`restartOnError=false`, and `waitForFinish=0`, then retain
the native run and storage IDs. It does not wait in a foreground tool call for
the Actor to finish. An accepted run is not completed output.

| Setting | Default | Meaning and accepted range |
|---|---|---|
| `APIFY_MCP_ENABLED` | `false` | Enables this mode's discovery and foreground run/read tools. |
| `APIFY_TOKEN` | Empty | This mode's Apify API token. |
| `APIFY_MAX_CHARGE_USD` | `1` | Per-run `maxTotalChargeUsd`; `0.001`–`1000`. |
| `APIFY_RUN_TIMEOUT_SECONDS` | `1800` | Provider run timeout; `1`–`3300` seconds. |
| `APIFY_MAX_MEMORY_MB` | `2048` | Ceiling for Actor memory; a whole power of two from `128`–`32768` MiB. Invalid ceilings or unsupported final allocations reject new starts before submission. An Actor requiring more than the ceiling is rejected. |
| `APIFY_POLL_SECONDS` | `30` | Background status-read interval; `1`–`300` seconds. Transient read failures back off up to 300 seconds. |
| `APIFY_RESULT_PAGE_SIZE` | `20` | Default number of dataset records fetched per page; `1`–`100`. |
| `APIFY_ALLOWED_ACTORS` | Empty | Additive, comma-separated exact native Actor IDs or `owner/name` exceptions for trusted community Actors. Empty permits official Apify-maintained Actors only; entries keep all official Actors eligible. |

The charge ceiling is sent for each new run, not a monthly account budget.
The 3,600-second Jarvis background deadline comes from the reviewed tool
manifest and includes queue time; it is separate from the provider's timeout.
Changing the poll interval does not extend either deadline.
Power-of-two checks apply only to new starts; discovery, reads, and recovery do
not allocate Actor memory.

## Optional background completion in Web

With the existing task worker ready, open **Settings → Tools → Background
tasks**, enable background admission, and select **apify_run_actor**. Both the
master switch and the saved tool selection are required. The feature can remain
enabled for ordinary foreground use while background admission stays off.
The existing production worker bindings require Linux, including Linux Docker
deployments; this does not add a native macOS or Windows background worker.

An eligible Web text request then receives the normal durable acceptance card.
The worker starts one native Apify run, saves its run ID, and observes that same
run. When it succeeds, the worker collects the first dataset page when one is
available. The existing task delivery system saves the result and returns a
late answer to the source conversation. A result-collection error keeps the
native run available for another read rather than starting the Actor again.

Status polling and worker heartbeats are separate. A long configured poll
interval does not stop lease renewal. After a worker restart, a saved native
checkpoint lets another worker resume observation with fresh ownership, the
original mode, and the original deadline. It does not submit another run or
reset the timeout.

If the worker stops during Actor preparation and no provider submission began,
the task ends as failed with an explicit notice that nothing was submitted.
It is not automatically retried. Once submission begins, uncertainty is handled
using the native-run rules below.

If submission may have reached Apify but no run ID was durably saved, the task
needs attention. Inspect the existing runs in Apify Console before deciding
what to do; Jarvis does not automatically submit again. An expired observation
deadline or lost status read is also not proof that remote work stopped.

Cancel requests target the saved native run. The task becomes cancelled only
after Apify confirms `ABORTED` for that run. `ABORTING`, closing the browser,
stopping the worker, or stopping a local process do not confirm cancellation.
Disabling new Apify submissions does not abandon an already accepted job;
observation still uses its saved mode's credential.

CLI, REST API, voice, workflow calls, and Web calls without eligible background
admission use the short foreground path. They receive a native run handle and
must use `apify_read_result` later. They do not receive automatic late delivery
or turn a running handle into a completed workflow result. This integration
needs no public callback URL or callback relay.

## Read results and additional pages

Use the real `run_id` from the accepted result. `apify_read_result` accepts
these argument objects; replace `YOURRUNID` with that saved ID.

```json
{"run_id":"YOURRUNID","action":"status"}
```

```json
{"run_id":"YOURRUNID","action":"dataset","offset":20,"limit":20}
```

```json
{"run_id":"YOURRUNID","action":"record","record_key":"OUTPUT"}
```

`status` reads current native state and storage handles. `dataset` reads the
default dataset, or a `dataset_id` belonging to that run, with a zero-based
`offset`, `limit` up to 100, and optional comma-separated `fields`. Continue
using the returned pagination offset and the same run ID. `record` reads a key
from the run's default key-value store; `OUTPUT` is the default key, but an Actor
may use a different one or have no such record. Binary records are saved to
Stash. A missing output is a reason to inspect the existing run and storage.

Apify's [dataset API](https://docs.apify.com/api/v2/dataset-items-get) returns
pages. Dataset counts can also lag briefly while the Actor is writing. Jarvis
retains the provider's counts and distinguishes a fetched page, its displayed
sample, and complete dataset coverage. A successful Actor may still have only
part of its dataset in the current result.

## Structured previews and retained output

Results use the shared `external_result_v1` JSON envelope. Provider/run IDs,
status, returned counts, total counts, offsets, and completeness come from
deterministic execution and reads. An LLM can summarize the returned evidence;
its prose does not replace this metadata or confirm a completed run.

`ok` confirms the tool call succeeded; `SUBMITTED` or `RUNNING` still means the
Actor has not finished. `result.complete` describes provider-result coverage,
while `sample_count` and truncation flags describe the preview. A complete
100-row fetched page can therefore have only five rows shown to the model.
Jarvis can read retained output or more pages of the same run when needed;
retrieving missing evidence is not a reason to submit another Actor run.

Web renders up to 20 preview rows in a generic table, with bounded JSON trees
for nested or mixed records, plain text previews, and authenticated Stash
downloads. Additional fields, depth, text, or rows can be omitted from the
preview with explicit truncation labels. Large integers that JavaScript cannot
represent exactly are shown as exact decimal strings; the raw JSON archive
retains the original numeric values.

The raw Stash record retains the fetched response or dataset page, not every
page in the remote dataset. Downloads retain their original cloud/local mode
after reloads or mode changes. Use `apify_read_result` for another page or
record; use the existing Stash tools to work with retained files. Normal Stash
retention applies, and a failed archive save does not advertise a nonexistent
download or repeat the Actor run.

Canvas creation is a separate tool call when requested. Actor runs and result
reads do not automatically create Canvas pages.

See also [remote MCP transport](MCP_REMOTE_TRANSPORT.md),
[tool management](../TOOL_MANAGEMENT.md),
[background tasks and recovery](../BACKGROUND-TASKS.md), and
[Stash](../STASH_SYSTEM.md).
