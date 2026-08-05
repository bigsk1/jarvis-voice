# SerpApi Tools

Jarvis provides a family of focused SerpApi tools for shopping, indexed-web
source discovery, local places, travel, and YouTube. Each tool has its own
schema and normalized result shape so Tool RAG can select a narrow capability
instead of routing every request through one ambiguous search tool.

`serpapi_amazon_search` is the renamed Amazon tool. Despite its former generic
name, its implemented product experience was Amazon-focused. It now accepts
only the `amazon` and `amazon_product` engines. Use `serpapi_search_index` to
discover general public webpages and source URLs.

## Tool catalog

| Tool | Provider engine(s) | Best use |
|---|---|---|
| `serpapi_amazon_search` | `amazon`, `amazon_product` | Amazon listing discovery, ASIN details, prices, ratings, Prime, delivery, stock, and product comparison |
| `serpapi_search_index` | `search_index` | Ranked indexed-web sources for grounding, datasets, and workflows; fetch returned URLs separately |
| `serpapi_ebay_search` | `ebay` | eBay listing discovery with price, condition, seller, shipping, images, and product IDs |
| `serpapi_ebay_product` | `ebay_product` | One eBay listing's focused details by numeric product ID |
| `serpapi_home_depot` | `home_depot`, `home_depot_product` | Home Depot products, price/rating comparison, store or ZIP availability, and focused details |
| `serpapi_maps_search` | `google_maps` | Places and local businesses with addresses, ratings, hours, phones, and websites |
| `serpapi_hotel_search` | `google_hotels` | Future lodging with stay dates, guests, prices, ratings, amenities, and property links |
| `serpapi_tripadvisor` | `tripadvisor`, `tripadvisor_place`, `tripadvisor_reviews` | Destination, hotel, restaurant, attraction, and forum discovery plus place details, nearby suggestions, and reviews |
| `serpapi_yelp_search` | `yelp`, `yelp_reviews` | Restaurants and local businesses with Yelp ratings, filters, price tiers, and optional review excerpts |
| `serpapi_youtube_search` | `youtube` | YouTube video discovery by keyword |
| `serpapi_youtube` | `youtube_video`, `youtube_video_transcript` | Video details and optional transcript fallback by URL or video ID |
| `flight_search` | `google_flights` or keyless `fast-flights` | Future airfare and itinerary options; see the [flight search guide](../flight-search-tool/README.md) |

There is no catch-all SerpApi live-web tool in this family. Search Index is for
source discovery; MCP Fetch or `crawl_url` is the normal follow-up when Jarvis
needs the contents of a returned page.

## Shared architecture

The family uses these common layers:

- `skills/*.tool.json` declares Tool RAG descriptions, schemas, availability,
  permissions, and the per-tool proxy policy.
- `skills/*.py` validates inputs, calls the appropriate SerpApi engine, and
  returns compact normalized JSON rather than raw provider payloads by default.
- `lib/serpapi_client.py` owns the HTTP request path, proxy integration,
  normalization helpers, and incident-aware provider diagnostics.
- `orchestrator/executor.py` owns subprocess timeouts and attaches bounded
  SerpApi status-page context after qualifying final failures.
- `jarvis-web/server/services/followup_extractor.py` preserves bounded result
  identity for later turns.
- `jarvis-web/client/js/structured-results.js` renders focused product, place,
  hotel, flight, Tripadvisor, Search Index, eBay, Yelp, Maps, and YouTube cards.

Raw provider JSON is available only through each tool's `include_raw` debug
option. Normal conversational and workflow calls should leave it off.

## Setup and mode-aware availability

Add the same credential independently to each mode that should expose the
tools:

```dotenv
SERP_API_KEY=your-key
```

Use `config/cloud.env` for cloud mode and `config/local.env` for local mode.
`JARVIS_DEFAULT_POSTAL_CODE` is optional and localizes Amazon delivery and Home
Depot availability where supported.

The eleven `serpapi_*` manifests declare:

```json
"availability": {
  "all_of_env": ["SERP_API_KEY"],
  "setup_hint": "Set SERP_API_KEY in the active mode env file."
}
```

When the resolved mode has no nonblank key:

- the tools are absent from the callable registry;
- Tool RAG sync excludes them and disables stale enabled database rows;
- a profile cannot force-enable them past the hard credential requirement;
- the Web Tools inventory may still show them disabled with a `needs config`
  badge; and
- verbose registry or sync output lists only the missing requirement name,
  never the secret value.

`flight_search` is the exception. It uses SerpApi Google Flights when the key
exists and a keyless `fast-flights` fallback otherwise, so its manifest is not
hard-gated by `SERP_API_KEY`.

After adding the key or changing manifests, sync each affected mode from the
operator environment used for Tool RAG embeddings:

```bash
cd ~/jarvis-voice
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

Restart or refresh the relevant Jarvis service after changing mode env files.

## Tool profiles

Profile overrides are a separate policy layer from credential availability.
The tracked examples under `skills/profiles/examples/` explicitly disable
SerpApi tools that do not fit the profile's purpose. In particular:

- local daily/minimal/research-lite profiles disable
  `serpapi_amazon_search`; Amazon shopping is not their general search route;
- offline, home, docs, creative, memory, and ops profiles disable the complete
  SerpApi family plus `flight_search` where public-network access is unwanted;
  and
- `research_pipeline` retains `serpapi_search_index` for source discovery but
  disables Amazon and the vertical tools.

Example profiles are templates. An already copied ignored runtime profile does
not automatically inherit later example changes, so merge or recopy it when
the profile policy changes.

## Proxy policy

Every SerpApi-backed manifest, including `flight_search`, explicitly defaults
to:

```json
"proxy_policy": "off"
```

Normal calls therefore run directly even if `LOCAL_PROXY`, `LOCAL_PROXY2`, or
conventional proxy variables are configured for other tools. The shared client
remains proxy-capable. A deliberate manifest change can opt one tool into:

- `inherit` — follow the configured shared proxy behavior;
- `prefer` — try the proxy chain and allow direct fallback; or
- `require` — require the proxy chain and fail closed.

See [HTTP proxy configuration](../../NETWORK_PROXY.md).

## Requests, cache, and quota

Most calls use one SerpApi search. Options that enrich results can consume
additional searches:

| Tool or option | SerpApi searches |
|---|---:|
| eBay search/product, Maps, Hotels, Search Index, YouTube search | 1 |
| Amazon listing or product call | 1 base call |
| Amazon empty-result query normalization | Up to 2 bounded retry calls |
| Amazon `include_product_details=true` | Up to `product_details_limit` additional product calls, maximum 5 |
| Home Depot `include_product_details=true` | 1 additional product call |
| Tripadvisor search with details and reviews | Up to 3 total calls |
| Tripadvisor details-only or reviews-only action | 1 |
| Yelp `include_reviews=true` | 2 total calls |
| YouTube `include_transcript=true` | 2 total calls |
| Flight search with SerpApi | 1 |
| Flight search keyless fallback | 0 |
| Settings → System Account API quota lookup | 0 |

Cached responses are allowed by default for the tools that expose `no_cache`.
Set `no_cache=true` only when the user explicitly needs a fresh provider scrape.
Home Depot intentionally stays on the cached path. Enrichment flags should be
enabled only when the extra detail is needed.

Jarvis Web calls SerpApi's free Account API only when Settings → System is
opened. A sanitized plan/monthly/hourly quota card is shown only after the
selected mode's `SERP_API_KEY` validates successfully; the response never
exposes the key, account ID, or email. Missing or invalid keys leave no card.

## Common usage

### Amazon listing discovery

```json
{
  "engine": "amazon",
  "query": "65W USB-C charger under $40",
  "num_results": 5
}
```

For a bounded value comparison with Prime, delivery, and stock signals:

```json
{
  "engine": "amazon",
  "query": "65W USB-C charger under $40",
  "num_results": 5,
  "include_product_details": true,
  "product_details_limit": 5
}
```

### Amazon product details

```json
{
  "engine": "amazon_product",
  "asin": "B072MQ5BRX"
}
```

The recommended flow is listing discovery first, then a focused ASIN lookup.
The tool preserves discovery URLs and merges detail rows by ASIN. Price,
rating, reviews, Prime, delivery, shipping, stock, availability, badges,
recent-purchase signals, and coupons remain unknown when SerpApi omits them.

### Search Index source discovery

```json
{
  "query": "PostgreSQL durable job queues",
  "mode": "standard",
  "num_results": 10
}
```

Use `mode=deep` when a workflow needs broader recall. Search Index returns
ranked titles, snippets, dates, languages, images, sitelinks, related queries,
pagination metadata, and exact URLs. It does not fetch page bodies. Pass a
chosen URL to MCP Fetch, `crawl_url`, a summarizer, Stash, or Canvas.

### eBay discovery and detail

```json
{
  "query": "ThinkPad X1 Carbon Gen 11",
  "buying_format": "BIN",
  "num_results": 5
}
```

Reuse a returned numeric `product_id` with `serpapi_ebay_product`:

```json
{
  "product_id": "123456789012"
}
```

### Home Depot

```json
{
  "query": "cordless drill",
  "delivery_zip": "97124",
  "sort_by": "top_rated",
  "num_results": 5
}
```

Pass `product_id` without a query for a focused product lookup. Set
`include_product_details=true` on a search only when full descriptions,
specifications, or larger images are needed.

### Maps and local places

```json
{
  "query": "coffee shops in Austin",
  "num_results": 5
}
```

Use Maps when address, phone, website, or hours matter. Use Yelp when Yelp
ratings, price tiers, attributes, or review excerpts are the primary signal.

### Hotels

```json
{
  "destination": "Phoenix, Arizona",
  "check_in_date": "2026-08-11",
  "check_out_date": "2026-08-13",
  "adults": 2,
  "max_price": 300,
  "rating": 8,
  "num_results": 5
}
```

Dates must be `YYYY-MM-DD`. Jarvis resolves relative dates before calling the
tool. The default is lowest complete-stay price; results are reference quotes
and the tool never books or pays.

### Tripadvisor

Discovery:

```json
{
  "action": "search",
  "query": "things to do in Rome",
  "category": "things_to_do",
  "num_results": 8
}
```

Focused follow-ups reuse the returned `place_id`:

```json
{"action": "details", "place_id": "187791"}
```

```json
{
  "action": "reviews",
  "place_id": "187791",
  "review_sort_by": "most_recent",
  "review_limit": 10
}
```

Search can set `include_details` and `include_reviews`, but each enrichment is
an additional paid request. Vacation Rentals are intentionally unsupported
because Tripadvisor discontinued that API surface.

### Yelp

```json
{
  "find_desc": "Coffee",
  "find_loc": "New York, NY, USA",
  "dogs_allowed": true,
  "sort_by": "rating",
  "include_reviews": true
}
```

Yelp does not consistently return full addresses or hours; use Maps when those
fields are required.

### YouTube

Discover videos:

```json
{
  "search_query": "pepper fermenting hot sauce",
  "num_results": 5
}
```

Then pass a selected URL to `serpapi_youtube`, `youtube_transcript`, or
`youtube_video`. SerpApi detail/transcript fallback is useful when yt-dlp is
blocked by cookies, authentication, or transcript availability.

## Amazon workflow

The shared `data/workflows/serpapi_amazon_search.json` recipe runs
`serpapi_amazon_search`, saves a normalized text export to Stash, and creates a
Canvas comparison report. Supported explicit commands are:

- `/serpapi_amazon <query>`
- `/amazon_search <query>`
- `/serpapi <query>` for compatibility

The workflow helper model receives only the normalized Amazon rows and has
server-side tools disabled, so it cannot silently replace the deterministic
source step with another search provider.

## Follow-up context and Web UI

Jarvis keeps bounded identifiers from recent SerpApi results so follow-ups can
reuse the correct item or place instead of guessing:

- Amazon ASINs, links, images, prices, ratings, Prime, delivery, and stock;
- eBay and Home Depot product IDs;
- Maps, Yelp, and Tripadvisor place IDs;
- Search Index source URLs and pagination metadata;
- hotel property IDs and stay context; and
- YouTube video IDs and URLs.

The Web UI renders structured cards for result types that have dedicated
adapters. Links and image URLs remain available to later Stash and Canvas
actions.

## Incident-aware failures

After a final transient SerpApi failure or a tool-process timeout, Jarvis makes
one short, bounded request to SerpApi's public unresolved-incidents JSON
endpoint. If an unresolved incident matches the engine that failed, the result
includes `data.serpapi_incident`,
`failure_reason=active_provider_incident`, the latest provider update, the
status-page URL, and a recommendation to retry later.

Unrelated incidents do not replace the original error. Validation failures do
not trigger the status lookup, and status lookup failure is ignored.

## Troubleshooting

If a tool is missing or marked `needs config`:

1. Confirm `SERP_API_KEY` is nonblank in the active mode's env file.
2. Confirm the active tool profile does not set that tool to `false`.
3. Re-run `./bin/sync-tools.py <mode>` from `~/jarvis-venv`.
4. Restart or refresh the Jarvis service for that mode.

For request failures, inspect:

```bash
jq 'select((.tool_name // "") | startswith("serpapi_"))' \
  logs/tools/tool-calls-$(date +%F).jsonl
```

For flights, include `or .tool_name == "flight_search"` in the filter. Provider
status context appears only for qualifying transient failures and timeouts.

## Adding another SerpApi tool

An end-to-end addition should include:

1. A focused `skills/<name>.py` wrapper using `request_serpapi`.
2. A `.tool.json` manifest with an accurate Tool RAG description,
   `SERP_API_KEY` availability, and explicit `proxy_policy`.
3. Engine registration for incident matching in `lib/serpapi_client.py`.
4. A subprocess timeout when the tool can make multiple sequential calls.
5. Follow-up extraction and a structured-results adapter when results benefit
   from persistent identity or visual cards.
6. Explicit entries in narrow profile examples.
7. Focused tests plus `tests/test_serpapi_proxy_policy.py` coverage.

Keep each wrapper narrow. A provider's ability to accept many engines is not a
reason to expose an ambiguously named catch-all tool to Tool RAG.
