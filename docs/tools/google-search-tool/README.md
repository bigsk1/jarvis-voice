# Google Search

`serpapi_google_search` retrieves general Google Search results through
SerpApi's fixed `google` engine. It preserves the provider's panel structure
instead of flattening every response into organic links. Google may return
an answer box, knowledge graph, related questions, local results, Top Stories,
availability or other query-specific panels. A missing panel is not proof that
the real-world information does not exist.

Use this tool for Google-specific results or questions that depend on those
panels. `serpapi_search_index` searches SerpApi's separate index; shopping,
images, sports, news and other focused SerpApi tools remain available for
their own tasks. This tool discovers results and provider evidence; it does
not open the returned websites or operate a browser.

Web result sections start collapsed for every Google panel, including sources,
viewing offers, flight information and unfamiliar sections such as episode
guides. Expand a section to inspect its saved results; repeated calls remain
available without filling the conversation with open tool output.
Returned thumbnails appear beside readable result fields when available;
ordinary sources can use a smaller site icon when no thumbnail was supplied.
Familiar named-result arrays, including episode guides, share the same compact
card layout. Missing images do not trigger another search, and additional
fields remain available in collapsed details or the retained response.

## Setup

The tool uses the existing `SERP_API_KEY` in the selected mode's
`config/cloud.env` or `config/local.env`. No additional package, service, key
or environment setting is required. The tool manifest remains key-gated for
both actions, although reading a retained response makes no network request.
Profile and Web tool restrictions still apply. The default and Docker
profiles inherit the manifest; narrow example profiles and `openai_only`
disable this additional paid-search capability.
Copied runtime profiles are separate configuration: updating an example does
not merge it into an existing customized profile. Review and merge tool
overrides explicitly rather than replacing that profile.

After installing the manifest, refresh Tool RAG for the configured modes from
the operator environment and restart the relevant service. Follow the
[shared SerpApi setup instructions](../serp-api-tool/README.md#setup-and-mode-aware-availability).
Do not use the repo `.venv` for `bin/sync-tools.py`.

If Prompt Guard is enabled, include `serpapi_google_search` in the selected
mode's existing `PROMPT_GUARD_TOOLS` list; both starter settings include it.
The shared executor screens returned search previews and `read_result`
excerpts before they enter the conversation model's context. It does not
scan the complete retained JSON when saving it or follow `raw_ref` itself.
The scanner's existing size limits and fail-open behavior still apply; see
[Prompt Guard coverage](../../PROMPT_GUARD.md#initial-coverage).

## Search

```json
{
  "action": "search",
  "query": "Hades II platforms",
  "limit": 10
}
```

`search` is the default action. Each call makes one Google Search request;
the tool does not automatically fetch another page, change engines, or query
more sources. Cached responses are allowed by default. Setting `no_cache`
to `true` bypasses the provider cache and can consume an additional search.
SerpApi's exact-parameter cache expires after one hour; see its
[cache parameter documentation](https://serpapi.com/search-api).
For current/live flight status, set `no_cache: true` and report the flight
date, timezone and source `updated_at`. A fresh Google fetch can still contain
older flight-source data; the search timestamp is not the flight status update
time. Reading the retained result never refreshes either timestamp.

Search accepts:

| Argument | Behavior |
|---|---|
| `query` | Required search text. |
| `country`, `language` | Default `us` and `en`. |
| `location` | Explicit location, otherwise the existing Jarvis default location or postal code; omitted when none is configured. An explicit non-US country without an explicit origin omits the US default location. |
| `uule` | Optional Google encoded location. |
| `device` | Defaults to `desktop`. |
| `start` | Provider result offset; defaults to `0`. Use a returned `pagination.next_start` to request another remote page. |
| `safe` | Defaults to `active`. |
| `tbs`, `kgmid` | Optional Google filter or knowledge-graph identifier. |
| `no_cache` | Defaults to `false`. |
| `extra_params` | Bounded scalar Google parameters. Core query, authentication, engine, output, async and response-restriction controls cannot be overridden. |
| `limit` | Preview rows per panel, default `10`, range `1–50`. This does not promise that Google returned that many rows. |
| `max_chars` | Preview budget, default `20000`, range `2000–60000`. Larger previews still share the caller's model/context budget. |

Completion Guard includes one shared Google evidence projection across its
effective-evidence and result-data sections. Repeated copies of an archive
share that budget; distinct archive/read receipts remain available. Other-tool
excerpts keep their existing section caps.

The result uses the shared `external_result_v1` contract, with
`source.provider: "serpapi"`, `source.tool: "serpapi_google_search"`, and
`result.kind: "google_search"`. It keeps the query, search URL, search time,
request localization/device, and a `panels` inventory. Each panel records its
native key and JSON Pointer path, type, count when applicable, bounded
preview, preview count, and truncation state. Provider pagination is separate
from local preview truncation.

`inventory_complete` distinguishes a complete section list from shortened
previews. When it is true, an absent panel was not returned by Google; reading
the root again cannot uncover it. Start with a short, specific entity and intent.
If a desired panel is absent, refine the query concisely or inspect an observed
source URL. Avoid piling guessed provider names into the query. Read a named
section when its preview omits relevant details.

`raw_ref` identifies the retained provider JSON in Stash. Read it for omitted
fields or rows before repeating a paid search. A preview is not a complete
copy of every returned panel, and Google result estimates are not counts of
locally retained records. Normal Stash retention applies.

For broader analysis, the existing `text_summarizer` tool accepts
`stash_ref: "<raw_ref>"` and an optional `focus`. It reads the original saved
artifact directly. Use JSON section reads for exact offers, prices, identifiers
and counts; a generated summary is a separate interpretation of that evidence.
Its internal model input currently bypasses the shared tool-result scan;
selecting `stash` or the Google tool for Prompt Guard does not screen this
internal file read. Use the Google tool's `read_result` action for excerpts
that pass through the configured tool-result screening boundary.

The search HTTP allowance is 90 seconds; the executor allows 120 seconds for
the request, retention and process cleanup. Qualifying transient search
failures can include the existing Google Search incident diagnostics.

## Read retained panels

Use the exact `raw_ref` from the earlier result. This action reads the saved
JSON without calling SerpApi or fetching a website:

```json
{
  "action": "read_result",
  "raw_ref": "stash://space_example/f_saved_google_response",
  "path": "/available_on",
  "offset": 0,
  "limit": 20,
  "max_chars": 20000
}
```

Choose a path from the saved panel inventory. `path` is a JSON Pointer,
not a dotted property name: `/knowledge_graph/description` selects a nested
field, and numeric segments select array entries. Escape a literal `~` as
`~0` and `/` as `~1` inside a segment. Omitting `path` or passing `""`
inventories the saved root.

`offset` and `limit` page through the selected local array or object. The
result reports `selected_path`, `offset`, `returned_count`, `has_more` and
`next_offset`. Continue with the returned local `next_offset` until the
needed rows are covered. This pagination is distinct from search
`pagination.next_start`, which starts another provider request.

Text selections use character offsets and the requested `max_chars` budget.
Reads also retain the original section inventory and movie/entity identity.
If an indivisible value such as an opaque URL cannot fit, the result explicitly
reports `page_blocked_by_budget` with no advancing cursor; increase the budget
or use Stash rather than repeating the same nonadvancing read.

For a question such as “what platforms did that result list?”, inspect
the prior response's relevant panel first. If Google did not return such a
panel, examine another saved path or open an observed source URL with an
existing fetch/browser tool. Do not invent a panel, its contents, or a source
URL. Missing/expired archives or invalid paths return an error; they never
fall back to a new search, including when provider-status diagnostics are
enabled. Archive reads retain the executor's normal 60-second cloud or
75-second local allowance.
