# Apify: discover Actors and run them through one gateway

Jarvis discovers Apify-maintained Actors and explicitly trusted community
Actors, then uses the hosted [Apify MCP server](https://docs.apify.com/mcp) to
inspect inputs, outputs, and pricing. Policy-aware search uses the Apify Store
API behind the existing `mcp_apify_search-actors` tool name. Two Jarvis tools
handle execution and results for eligible, ordinary, limited-permission Actors:
`apify_run_actor` and `apify_read_result`. Each Actor supplies its own input
schema; adding another Actor does not require another tool, frontend adapter,
or Tool RAG entry. Reviewed property Actors additionally share readable listing
cards and a compact, provider-neutral property projection.

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
against their title, name, description, README summary, and publisher. Keep
keywords focused. Exception metadata reads share the search call's time budget.
An incomplete or failed exception lookup marks the result partial, with no
combined total or next-page offset; a later nonzero offset cannot return a
reliable merged page. Configured trusted Actors remain available for direct
details lookup and run preparation even when discovery is partial.

### Store API search migration: November 15, 2026

The [October 30 migration notice](https://apify.com/change-log/apify-store-api)
announces a new Store backend on November 15. Keyword searches ignore upstream
offsets, return at most 100 candidates, and report returned counts rather than
the number of catalog matches. `sortBy` is ignored for all Store calls. Jarvis
does not send it or attempt to page upstream keyword searches.

For nonblank `keywords`, Jarvis fetches one official relevance window at offset
zero and applies its existing `limit`/`offset` locally after matching trusted
exceptions. `pagination.scope` is `search_window`; `source_limit` is 100 and
`window_items` counts the combined window when all reads succeeded, and
`offset_applied_locally=true` distinguishes Jarvis's paging from the upstream
API's ignored offset. The result policy names `apify_run_actor` as the generic
execution tool; separate Actor tools are not required.
Jarvis replaces the hosted search description and parameter guidance for this
native bridge, so upstream instructions about dedicated Actor tools or ignored
search offsets do not override Jarvis's actual execution and paging behavior.
`total_items` stays unknown and `complete=false`, including empty or short
windows. `has_more=false` means the current window ended; refine keywords for
other matches. This is not proof that the entire Store was searched. Rankings
can be personalized and cached for five minutes, and separate requests do not
form a saved snapshot.

Blank or whitespace-only keywords omit the upstream `search` parameter and
retain normal Store listing pagination and totals. The native `username=apify`
filter remains in place for both paths. New category IDs and pricing filters
do not change this trust policy; Jarvis keeps the existing public search inputs.

Ratings come from nested `stats`; optional usage metrics may be absent. New
`isVerified` values are advisory, and `readmeSummary` supplies a bounded fallback
when the description is empty. Empty titles fall back to the native Actor name.
None of these fields grants execution permission. Store pricing metadata is a
discovery hint: inspect current Actor details/pricing before a paid run, since
pricing-related filters can lag recent changes. Run limits are unchanged.

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
| `APIFY_GEOCODER_URL` | `https://nominatim.openstreetmap.org/search` | Nominatim-compatible HTTPS endpoint used only by Zillow criteria preparation. Credentials/query strings in the configured URL are rejected. |
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
must use `apify_read_result` to collect it. They do not receive automatic late delivery
or turn a running handle into a completed workflow result. This integration
needs no public callback URL or callback relay.

## Zillow searches by criteria

For `maxcopell/zillow-scraper`, supply `search` instead of `input` to express the
requested location, listing status, price, property types and listing age.
The dedicated Zillow adapter resolves verified location bounds and constructs
URLs with mutually exclusive sale/rental/sold flags;
the model does not need to visit Zillow in a browser or invent region IDs,
map boundaries, or encoded `searchQueryState` filters.

```json
{
  "actor": "maxcopell/zillow-scraper",
  "search": {
    "locations": ["Albany, OR", "Lebanon, OR"],
    "listing_status": "for_sale",
    "property_types": ["single_family"],
    "price_min": 300000,
    "price_max": 600000,
    "max_days_on_zillow": 60,
    "results_per_location": 10
  }
}
```

City/ZIP bounds come from a cached, Nominatim-compatible US location lookup
(default: OpenStreetMap Nominatim). Requests share a process-safe one-per-second
limit and successful results cache for 180 days under ignored `data/cache/`.
`APIFY_GEOCODER_URL` selects another compatible HTTPS endpoint without code
changes. There is no new API key, dependency installation, service or database.
Ambiguous/unavailable location lookups fail before a paid Actor submission.
Raw `input` skips this lookup. Bounds are map rectangles, rather than exact city
polygons, so nearby places can appear. Attribution: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
After a compiler-assisted submission, the same ignored geography cache retains
the source credit keyed by mode, native run ID and Actor ID. It contains no
token or search input. Later result reads copy that known attribution into the
retained page, so Canvas and PDF exports can credit the lookup after the
original tool process exits. Ordinary raw-input and unknown legacy runs do not
receive guessed attribution. A cache-write failure preserves the accepted run
handle and never causes another submission.

Website filtering remains external behavior: inspect returned city, status, price, type and age before saying the
criteria matched. A missing age or price is unknown. A result limit can prevent
exhaustive coverage. Other Actors keep their native `input` schema; every caller
must provide exactly one of `input` or `search`. Permission, build, resource and
billing checks apply to either form, including optional background execution.

## Read results and additional pages

Use the real `run_id` from the accepted result. `apify_read_result` accepts
these argument objects; replace `YOURRUNID` with that saved ID.

```json
{"run_id":"YOURRUNID","action":"status"}
```

```json
{"run_id":"YOURRUNID","action":"collect","wait_seconds":30,"limit":20}
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

`collect` observes the saved run for at most `wait_seconds` (0–60; default 30),
then fetches one dataset page if it succeeded. A still-running result preserves
the same handle for a later collection; it is not completed scraping. Failed or
cancelled runs retain their native status. Collection never starts another run.
Its foreground subprocess allowance is 150 seconds, leaving room for the final
bounded HTTP response and dataset reads. Long-running Actors still need later
collection or the optional background observer.

Apify's [dataset API](https://docs.apify.com/api/v2/dataset-items-get) returns
pages. Dataset counts can also lag briefly while the Actor is writing. Jarvis
retains the provider's counts and distinguishes a fetched page, its displayed
sample, and complete dataset coverage. A successful Actor may still have only
part of its dataset in the current result.

## Structured previews and retained output

Results use the shared `external_result_v1` JSON envelope. Provider/run IDs,
status, returned counts, total counts, offsets, and completeness come from
deterministic execution and reads. An LLM can summarize the returned evidence;
its prose does not replace this metadata or confirm a completed run. Dataset metadata is observed after fetching
the page; a total smaller than the observed page range becomes unknown rather
than displaying an impossible zero or claiming complete coverage.

`ok` confirms the tool call succeeded; `SUBMITTED` or `RUNNING` still means the
Actor has not finished. `result.complete` describes provider-result coverage,
while `sample_count` and truncation flags describe the preview. A complete
100-row fetched page can therefore have only five rows shown to the model.
Jarvis can read retained output or more pages of the same run when needed;
retrieving missing evidence is not a reason to submit another Actor run.

Reviewed Zillow and Redfin output renders property cards with price, address,
location, status, beds/baths, area, listing age when known, property links and
available safe HTTPS photos. Native IDs remain in secondary run details.
Unsupported Actor/output shapes retain generic previews. Web renders up to 20
preview rows, with authenticated Stash downloads. Additional fields, depth,
text, or rows can be omitted from the
preview with explicit truncation labels. Large integers that JavaScript cannot
represent exactly are shown as exact decimal strings; the raw JSON archive
retains the original numeric values.

**Browse saved page** loads the already fetched archive through authenticated,
saved-mode Stash access and pages its property rows locally. Browsing does not
call Apify or a model. The displayed preview, fetched page and remote dataset
total have separate counts; fetching 100 records does not mean all 100 fit into
a model preview. Property archives retain both the original native records and
compact normalized `presentation.items` for analysis or a Canvas report.

Saved follow-ups keep one bounded preview per native mode/run/dataset, with
`retained_pages` identifying every fetched page that cannot safely be deduplicated.
Each entry keeps its own offset, returned count, selected fields when known, and
raw Stash reference; the preview's counts still describe that one page, not a
merged dataset. The latest observed native status and its `status_raw_ref` survive
status-only reads, including failure after data was fetched. Separate runs,
datasets and named output records remain separate. Read the retained pages for
more detail, or continue with `pagination.next_offset`. A pathological manifest
that exceeds the follow-up budget is explicitly marked `retained_pages_truncated`;
its `retained_pages_count` includes the omitted references. Changing selected
columns is not a reason to repeatedly fetch overlapping pages.

The raw Stash record retains the fetched response or dataset page, not every
page in the remote dataset. Downloads retain their original cloud/local mode
after reloads or mode changes. Use `apify_read_result` for another page or
record; use the existing Stash tools to work with retained files. Normal Stash
retention applies, and a failed archive save does not advertise a nonexistent
download or repeat the Actor run.

Canvas creation is a separate tool call when requested. Actor runs and result
reads do not automatically create Canvas pages. Pass all relevant retained `raw_ref` / saved `source.mode` pairs to the Canvas
tool's `property_sources` argument. It reads full fetched pages, normalizes and
deduplicates exact listing identities, and embeds a self-contained property
report with photos, city counts, search, sorting, cards and a table. The model
does not need to copy rows from its shortened preview. A saved report survives
Stash expiry. See [Canvas property reports](../CANVAS_SYSTEM.md#property-listing-reports). Scheduled workflows use these same foreground input/result
contracts: a submission step alone is not a completed monitoring report. They
must collect the run and handle pagination/limits, unknown fields, and provider
failures explicitly. Calling a property “new this week” additionally requires
evidence from listing age or a saved comparison baseline; it cannot be inferred
from a successful run or a small sample.

See also [remote MCP transport](MCP_REMOTE_TRANSPORT.md),
[tool management](../TOOL_MANAGEMENT.md),
[background tasks and recovery](../BACKGROUND-TASKS.md), and
[Stash](../STASH_SYSTEM.md).
