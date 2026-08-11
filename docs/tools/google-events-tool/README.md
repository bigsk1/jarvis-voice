# Google Events tool

`serpapi_google_events` is Jarvis's focused event-discovery tool. It calls
SerpApi's `google_events` engine once and returns a bounded, normalized event
shortlist suitable for a standalone answer, later follow-up turns, Web UI cards,
or workflow handoffs.

SerpApi requires the desired event city in `q`; its separate `location`
parameter controls where the Google search originates. Jarvis handles both:
it appends the resolved location to ordinary event keywords and also sends that
location as the search origin. See the official
[Google Events API documentation](https://serpapi.com/google-events-api) and
[event result schema](https://serpapi.com/events-results).

## Location behavior

Location precedence is deterministic:

1. The tool call's `location`.
2. `JARVIS_DEFAULT_LOCATION` from the active mode env file.
3. `JARVIS_DEFAULT_POSTAL_CODE` from the active mode env file.
4. An error before the network request when none is configured.

An advanced `uule` can replace `location`, but the two cannot be combined. A
human-readable event city must already be in `query` when `uule` is used.

Use a qualified city whenever more than one place shares the name:

```json
{"query": "food festivals", "location": "Portland, Oregon"}
```

```json
{"query": "food festivals", "location": "Portland, Maine"}
```

The tool never rewrites bare `Portland` to a guessed state. It returns
`location_ambiguity_warning` so the response model can ask for or disclose the
missing qualifier. If a complete query already contains a location, such as
`concerts in Portland, Maine`, Jarvis does not append the default location a
second time.

## Filters and pagination

```json
{
  "query": "family-friendly events",
  "date_filter": "week",
  "max_results": 10
}
```

Supported date values are `today`, `tomorrow`, `week`, `next_week`, `month`,
and `next_month`. Set `virtual: true` for online-only results; it can be combined
with a date filter. Pagination uses offsets `0`, `10`, `20`, and so on. When the
provider exposes another page, reuse the returned `next_start`.

`no_cache` defaults to false. SerpApi documents an exact-parameter cache with a
one-hour lifetime and says cached searches do not consume monthly searches.

## Result shape

Each normalized `results[]` row can include:

- title, type, `start_date`, `when`, date text, and time;
- venue name/rating/reviews and a public venue link;
- structured address plus `address_text`;
- a bounded description and listed price;
- ticket or more-info sources and public links;
- public Google map link/image plus event thumbnail/image.

Jarvis omits SerpApi drill-down and archive URLs from normal rows. Full provider
JSON is available only with `include_raw: true` for debugging. Event
descriptions and linked content are marked as untrusted external content.

## Standalone and chained use

Examples:

```text
Find live music this week near me.
```

```text
Find family events tomorrow in Portland, Maine.
```

After event discovery, Jarvis can use the returned venue or address with:

- `serpapi_google_local` for nearby restaurants, parking, or businesses;
- `serpapi_tripadvisor` for destination activities and reviews;
- `serpapi_maps_search` for map-centered place exploration;
- `weather` when outdoor conditions affect the plan;
- `canvas`, `stash`, or `workflow` for durable itineraries and scheduled runs.

All tools remain separate and optional. The Events tool requires only a
nonblank `SERP_API_KEY`; its manifest is automatically excluded from Tool RAG
when that key is unavailable or the active profile disables it.
