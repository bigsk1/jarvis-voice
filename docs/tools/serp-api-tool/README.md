# SerpApi Tools

Jarvis provides a family of focused SerpApi tools for shopping, indexed-web
source discovery, existing-image discovery, news, trend analysis, events, local
places and restaurant reviews, sports, travel, and YouTube. Each tool has its own schema and normalized result shape so
Tool RAG can select a narrow capability instead of routing every request through
one ambiguous search tool.

`serpapi_amazon_search` is the renamed Amazon tool. Despite its former generic
name, its implemented product experience was Amazon-focused. It now accepts
only the `amazon` and `amazon_product` engines. Use `serpapi_search_index` to
discover general public webpages and source URLs.

## Tool catalog

| Tool | Provider engine(s) | Best use |
|---|---|---|
| `serpapi_amazon_search` | `amazon`, `amazon_product` | Amazon listing discovery, ASIN details, prices, ratings, Prime, delivery, stock, and product comparison |
| `serpapi_google_shopping_light` | `google_shopping_light` | Fast multi-retailer product discovery and price comparison with merchant, delivery, rating, sale, thumbnail, offer links, and Immersive Product handoff tokens |
| `serpapi_google_immersive_product` | `google_immersive_product` | Rich detail for one selected product: specifications, review insights, user reviews, media, variants, and expanded store offers |
| `serpapi_google_sports` | `google_sports` plus conditional `google` resolver | Current game schedules and scores, game details, standings, players, brackets, league statistics, and rankings |
| `serpapi_search_index` | `search_index` | Ranked indexed-web sources for grounding, datasets, and workflows; fetch returned URLs separately |
| `serpapi_google_images_light` | `google_images_light` | Existing web images with full-size URLs, thumbnails, source pages, dimensions, usage-rights filters, and pagination |
| `serpapi_google_news_light` | `google_news_light` | Fast topic-specific recent news, grouped Top Stories, source URLs, localization, and result-offset pagination |
| `serpapi_google_trends` | `google_trends` | Interest over time for named topics, comparisons by region, and rising/top related queries or topics for monitoring and workflows |
| `serpapi_google_trending_now` | `google_trends_trending_now`, `google_trends_news` | Discover current trends without a seed topic, then retrieve associated news for one selected trend token |
| `serpapi_ebay_search` | `ebay` | eBay listing discovery with price, condition, seller, shipping, images, and product IDs |
| `serpapi_ebay_product` | `ebay_product` | One eBay listing's focused details by numeric product ID |
| `serpapi_home_depot` | `home_depot`, `home_depot_product` | Home Depot products, price/rating comparison, store or ZIP availability, and focused details |
| `serpapi_google_events` | `google_events` | Upcoming local or virtual events with dates, venues, descriptions, ticket sources, public maps, images, date filters, and active-mode location fallback; see the [Google Events guide](../google-events-tool/README.md) |
| `serpapi_google_local` | `google_local` | Google Local business listings near an explicit or mode-default location, with ratings, hours, service options, ads, related place searches, and pagination |
| `serpapi_google_local_services` | `google_local_services` plus conditional `google_maps` resolver | Screened US professional-service providers, Google badges, contact and availability details, and provider drill-down |
| `serpapi_maps_search` | `google_maps` | Places and local businesses with addresses, ratings, hours, phones, and websites |
| `serpapi_hotel_search` | `google_hotels` | Future lodging with stay dates, guests, prices, ratings, amenities, and property links |
| `serpapi_travel_explore` | `google_travel_explore` | Flexible destination discovery from an origin with suggested dates, headline flight/hotel planning prices, and exact airport handoffs; see the [Travel Explore guide](../travel-explore-tool/README.md) |
| `serpapi_tripadvisor` | `tripadvisor`, `tripadvisor_place`, `tripadvisor_reviews` | Destination, hotel, restaurant, attraction, and forum discovery plus place details, nearby suggestions, and reviews |
| `serpapi_open_table_reviews` | `open_table_reviews` | Paginated OpenTable diner reviews, rating summaries, category ratings, restaurant responses, and photos by restaurant ID or URL; JSON, HTML, or Markdown output |
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
- `lib/stash_helper.py` owns strict public-image download validation and bounded
  raster normalization used by Google Images Stash saves and public
  `generate_image` references; Stash saves also persist durable source/final-URL
  provenance.
- `orchestrator/executor.py` owns subprocess timeouts and attaches bounded
  SerpApi status-page context after qualifying final failures.
- `jarvis-web/server/services/followup_extractor.py` preserves bounded result
  identity for later turns.
- `jarvis-web/client/js/structured-results.js` renders focused product, place,
  image-gallery, multi-retailer shopping, hotel, Travel Explore, flight,
  Tripadvisor, Google Events, Google
  Local, Google Local Services, Google News Light, Google Shopping Light,
  Google Immersive Product, Google Trends, Trending Now,
  Google Sports, Search Index, eBay, OpenTable Reviews, Yelp, Maps, and YouTube cards.

Raw provider JSON is available only through each tool's `include_raw` debug
option. Normal conversational and workflow calls should leave it off.
`serpapi_open_table_reviews` and `serpapi_google_immersive_product` additionally
support explicit HTML and Markdown provider output; both remain labeled and
handled as untrusted external content.

## Setup and mode-aware availability

Add the same credential independently to each mode that should expose the
tools:

```dotenv
SERP_API_KEY=your-key
```

Use `config/cloud.env` for cloud mode and `config/local.env` for local mode.
`JARVIS_DEFAULT_LOCATION` and `JARVIS_DEFAULT_POSTAL_CODE` can localize Google
Shopping Light when no location is supplied. The postal code also localizes
Amazon delivery and Home Depot availability where supported.

The twenty-three `serpapi_*` manifests declare:

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
| eBay search/product, Google Shopping Light, Google Immersive Product, Google Local, Maps, Hotels, Travel Explore, Search Index, Google Images Light, Google News Light, Google Trends, Trending Now discovery, Trending Now news drill-down, YouTube search | 1 |
| Normal Google product discovery plus rich detail | 2: Shopping Light plus Immersive Product |
| Google Local Services with explicit `data_cid` or a built-in New York, Austin, or Portland alias | 1 |
| Google Local Services with any other explicit or mode-default location | 2: Google Maps CID resolution plus Local Services |
| Amazon listing or product call | 1 base call |
| Amazon empty-result query normalization | Up to 2 bounded retry calls |
| Amazon `include_product_details=true` | Up to `product_details_limit` additional product calls, maximum 5 |
| Home Depot `include_product_details=true` | 1 additional product call |
| Tripadvisor search with details and reviews | Up to 3 total calls |
| Tripadvisor details-only or reviews-only action | 1 |
| OpenTable Reviews JSON, HTML, or Markdown page | 1 |
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

### Google Shopping Light

Search multiple retailers for current offers without the slower rich Google
Shopping response:

```json
{
  "query": "Sony WH-1000XM6 headphones",
  "country": "us",
  "max_price": 450,
  "sort_by": "price_low_to_high",
  "max_results": 10
}
```

The tool combines regular, inline, and categorized shopping sections into one
deduplicated shortlist. Each offer can retain its merchant, current and prior
price, numeric price, rating and review count, delivery, sale tag, installment
summary, thumbnail, product ID, and direct merchant or Google product link.
`location` defaults to `JARVIS_DEFAULT_LOCATION`, then
`JARVIS_DEFAULT_POSTAL_CODE`, when either is configured in the active mode. If
neither exists, SerpApi's provider location is used.

Use `on_sale=true`, `free_shipping=true`, or price bounds for a narrow search.
The returned `lowest_returned_price` is only the lowest listing in the bounded
result set—not proof that differently configured products are equivalent.
Verify model, size, condition, seller, shipping, tax, and availability before
calling an offer the best deal. Comparison workflows can pass the compact
candidate rows directly to later ranking, Canvas, or reporting steps. Use
`serpapi_amazon_search` instead when Amazon-specific Prime, delivery, stock, or
ASIN detail is required.

Eligible Shopping Light rows also preserve
`immersive_product_page_token` and `serpapi_immersive_product_api`. Those are
provider-generated product locators for a second, explicit detail call; they
are not browser session state and must not be guessed, decoded, or constructed
from a product name or Google product ID.

### Google Immersive Product

Use this after selecting an exact Shopping Light result when the user needs
product specifications, features, review themes, user reviews, product media,
variants, or richer store comparisons:

```json
{
  "page_token": "<immersive_product_page_token from the selected result>",
  "more_stores": true,
  "max_stores": 13
}
```

`more_stores=true` is the default and asks SerpApi for up to 13 offers in the
single detail search. The result preserves `stores_next_page_token` for an
explicit later store page and exposes provider tokens embedded in returned
variant or related-product handoff links. It does not automatically paginate,
switch variants, or enrich every discovery candidate, so a normal discovery
plus selected-product detail request costs two searches.

The manifest lists `serpapi_google_shopping_light` as a soft prerequisite so
Tool RAG can show both schemas when only a product name is known. Availability
remains independent: if Shopping Light is disabled but a verified token is
already available from history, a workflow, the user, or another provider
response, Immersive Product can still run. Workflows that require discovery
must keep Shopping Light as their own required step. JSON is the normal format;
HTML and Markdown remain explicitly untrusted external content.

### Google Sports

Ask for a team or league schedule with a normal query:

```json
{
  "query": "Los Angeles Lakers",
  "sport": "basketball",
  "entity_type": "team",
  "tab": "games",
  "max_results": 10
}
```

The Google Sports engine requires a Google Knowledge Graph ID. When `kgmid` is
omitted, Jarvis performs one bounded `google` resolver request and then the
`google_sports` request, so `serpapi_searches_used` is normally `2`. A workflow
can pass a known `kgmid` directly for a deterministic one-search call.

League and team views support `games`, `standings`, `players`, and `brackets`;
league views additionally support `stats` and `rankings`. Game entities need no
tab except the optional American-football `overview`. Returned rows normalize
matchups, scores, status and dates, team and game KGMIDs, league/venue details,
standings statistics, players, highlights, and season KGMIDs. Follow-ups can use
those exact IDs to switch views or seasons without repeating entity discovery.

A direct game result also preserves returned season records and line or period
scores, normalized full `box_score` rows, compact `box_score_highlights`, official
`more_info` links, and `watch` choices for upcoming or ongoing games. Availability
depends on the sport, game state, market, and Google's response. Treat the compact
highlight list as a ranking aid and use the full player rows when explaining why a
performance mattered.

Without a time filter, team and league game results are selected around the
current UTC time instead of taking the oldest edge of Google's returned
schedule. The normalized list puts recent games newest-first, then fills the
remaining result budget with the nearest upcoming games. `selection_mode` and
`selection_anchor` make that choice explicit in tool and follow-up context.

For bounded game windows, use `middle_time`, or combine `after_time` and
`before_time`, with UTC values such as `2026-08-05T12:30:00Z`. Results are live
sports data, while general coverage and commentary belong in
`serpapi_google_news_light`.

For a readable drill-down, use `/game_brief <sport> <team>`, such as
`/game_brief baseball Los Angeles Dodgers`. The recipe makes Google Sports the
required factual source and can optionally use Brave LLM Context, Brave MCP
search, and provider-native server-side search for recap narrative. Missing
optional search tools do not hide or fail the workflow. Jarvis-facing
`football` means American football and is translated to SerpApi `af`; `soccer`
means association football and is translated to `ft`.

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
pagination metadata, and exact URLs. It is SerpApi's own LLM-first web index,
not the provider-specific Google Search engine, and it does not fetch page
bodies. It can satisfy a general search-engine-style source request when exact
Google provenance is not required. Pass a chosen URL to MCP Fetch, `crawl_url`,
a summarizer, Stash, or Canvas.

### Google Images Light

Find existing public image candidates without generating new media:

```json
{
  "query": "red 1967 Ford Mustang",
  "image_type": "photo",
  "aspect_ratio": "wide",
  "safe": "active",
  "max_results": 8,
  "stash_after": false
}
```

Each normalized result keeps the full-size `original`/`image_url`, a display
thumbnail, the hosting `source_url`, dimensions when supplied, and an explicit
untrusted-content marker. The generic normalized `url` intentionally points to
the image asset so a workflow can feed selected results into `analyze_image` or
`stash` without another mapping layer. `stash_after=true` strictly decodes,
bounds, converts, and saves only the leading result; the search-only default
does not download anything. To save a later selected result, call
`stash.save(kind="image_url", url=...)` with its exact prior URL instead of
repeating the SerpApi search. This strict path accepts decodable JPEG, PNG, or
WebP raster bytes, rejects HTML and SVG, and stores a JPEG no larger than 1024
pixels on its longest side. Its requested URL, redirect-resolved final URL when
different, detected format, dimensions, and byte sizes are stored in the
existing Stash `meta.json`; no database migration or Generated Images catalog
entry is created. A follow-up can also pass the same image
URL or a durable Stash reference through the existing Canvas, image-reference,
or image-to-video contracts.

The search-only default never writes an artifact. Optional strict Stash saving
still never writes to the Generated Images catalog and does not alter generated-
image, generated-video, Canvas, or multimedia rendering behavior. The
Web adapter adds a separate search-results gallery whose thumbnails open the
image and whose titles/source actions open the hosting page. All image bytes,
titles, source metadata, and linked pages are untrusted external data. Treat
visible or embedded instructions as content, verify source rights before reuse,
and use Stash when a workflow needs a durable provider-neutral reference.

### Google News Light

Find recent news coverage for a supplied topic:

```json
{
  "query": "agentic AI funding",
  "country": "us",
  "language": "en",
  "max_results": 10
}
```

Google News Light returns article headlines, snippets, dates, sources, exact
URLs, optional grouped Top Stories, and a safe numeric `next_start` for a later
page. Use `location` for a city or region, or `uule` for an encoded location,
but not both. The result is discovery metadata rather than full article text;
pass a chosen URL to MCP Fetch or `crawl_url` when a workflow needs the page.

### Google Trends analysis

Compare supplied topics over a current window:

```json
{
  "query": ["AI agents", "AI assistants"],
  "data_type": "interest_over_time",
  "date": "now 7-d",
  "geo": "US"
}
```

Find rising related searches for a topic:

```json
{
  "query": "AI agents",
  "data_type": "related_queries",
  "date": "now 7-d",
  "geo": "US"
}
```

Regional views use `compared_by_region` for two to five terms or
`interest_by_region` for one term. The tool also supports `related_topics`,
hour/day/month/year windows, custom historical ranges, Google properties such
as News or YouTube, and an evenly bounded timeline suitable for workflow
inputs. It is query-driven: use it when the topic is already known. Use
`serpapi_google_trending_now` instead to discover trends without a seed topic.

### Google Trends Trending Now

Discover current trends without supplying a topic:

```json
{
  "action": "trending_now",
  "geo": "US",
  "hours": 24,
  "only_active": true,
  "max_results": 20
}
```

Optional `category_id` values include `3` for business and finance, `7` for
health, `14` for politics, `17` for sports, `18` for technology, `19` for
travel, and `20` for climate. The discovery response includes search volume,
percentage growth, active state, category names, related searches, a public
Google Trends link, and an exact `news_page_token` for each result.

Retrieve articles only after selecting one trend:

```json
{
  "action": "news",
  "page_token": "<exact news_page_token from a trending_now result>",
  "trend_query": "selected trend label",
  "max_results": 10
}
```

News is deliberately not fetched automatically. Discovery costs one SerpApi
search; drilling into one selected trend's news costs one additional search.
The follow-up extractor preserves the exact token so requests such as “show me
the news behind the second trend” do not require another discovery call.

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

### Google Local and Maps

Use Google Local for nearby business discovery using the active mode's
configured location:

```json
{
  "query": "dog-friendly coffee shops",
  "max_results": 10
}
```

When neither `location` nor `uule` is supplied, the tool resolves
`JARVIS_DEFAULT_LOCATION` first and then `JARVIS_DEFAULT_POSTAL_CODE`. If all
four inputs are empty, it fails clearly instead of allowing proxy geography to
choose the search origin. An explicit `location` always wins. Results keep
ordinary and sponsored listings separate, label service options, preserve
Discover More Places suggestions, and return a numeric `next_start`.

Use Google Maps when a map-centered coordinate bias is more useful:

```json
{
  "query": "coffee shops in Austin",
  "num_results": 5
}
```

Use Yelp when Yelp ratings, price tiers, attributes, or review excerpts are the
primary signal.

### Google Local Services

Use Google Local Services for screened US professional-service providers rather
than ordinary nearby businesses:

```json
{
  "query": "electrician",
  "location": "Austin, Texas",
  "max_results": 10
}
```

The provider requires a numeric city or district `data_cid`; the discontinued
Google `place_id` parameter is not used. Supplying `data_cid` directly takes one
SerpApi search. New York, Austin, Portland, and their documented
built-in ZIP aliases are resolved locally and also take one search. Every other
location uses a bounded Google Maps lookup followed by Local Services and
returns `serpapi_searches_used: 2`. When both `data_cid` and `location` are
omitted, Jarvis uses `JARVIS_DEFAULT_LOCATION` and then
`JARVIS_DEFAULT_POSTAL_CODE`.

Google Local Services returns empty results outside the United States. Its
`query` must also describe a supported professional service, not a general
restaurant, store, or named-business query. The tool converts common natural
phrases to SerpApi's required identifier—for example, `car repair shop` becomes
`auto_repair_shop` and `house cleaner` becomes `cleaning_service`—and reports
that identifier as `provider_query`. Unsupported categories fail before using a
SerpApi search. The current canonical list is maintained on SerpApi's
[supported Google Local Services queries](https://serpapi.com/google-local-services-queries)
page.

Search results preserve the `cid`, `bid`, and `pid` tuple; pass all three with
the same query and city `data_cid` to retrieve the provider's checks, services,
description, website, images, and detailed hours.

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

### Travel Explore

```json
{
  "departure_id": "PDX",
  "travel_duration": "weekend",
  "interest": "beaches",
  "max_price": 300,
  "sort_by": "flight_price",
  "num_results": 5
}
```

Use `serpapi_travel_explore` when the destination or travel dates are still
flexible. It makes one `google_travel_explore` request and returns a bounded,
flat `results[]` shortlist. Each destination can include its Google location
ID, suggested dates, airport code, headline flight and hotel prices, flight
duration, stops, airline, coordinates, image, ground-transfer time, and public
Google Travel link.

This is a discovery tool, not exact shopping. Headline prices are provider
planning signals; the provider does not document the lodging price basis.
Suggested dates can also vary within the requested `weekend`, `one_week`, or
`two_weeks` bucket. After the user selects a destination, use `flight_search`
with the returned `airport_code`, `start_date`, and `end_date`, then use
`serpapi_hotel_search` with the destination name and the same dates. Use
`serpapi_tripadvisor` when the next question is about the destination itself.

`arrival_area_id` accepts a broad region or country KGMID such as `/m/02j9z`
for Europe. The Jarvis wrapper intentionally does not expose provider
`arrival_id`: a fixed destination belongs in the exact `flight_search` stage.
See the [focused Travel Explore guide](../travel-explore-tool/README.md) for
workflow fields and handoff examples.

### Google Events

```json
{
  "query": "live music",
  "location": "Portland, Oregon",
  "date_filter": "week",
  "max_results": 10
}
```

`serpapi_google_events` makes one `google_events` request and adds the resolved
city to the provider query. An explicit `location` wins; otherwise it uses
`JARVIS_DEFAULT_LOCATION`, then `JARVIS_DEFAULT_POSTAL_CODE`, from the active
mode env file. Qualify ambiguous cities: use `Portland, Oregon` or
`Portland, Maine`, not just `Portland`. A bare city remains callable but the
result includes `location_ambiguity_warning` rather than pretending Jarvis
knows which city was intended.

Date filters support `today`, `tomorrow`, `week`, `next_week`, `month`, and
`next_month`; `virtual: true` can be combined with any of them. Results retain
bounded event timing, venue, address, description, image, ticket-source, and
public map fields. Use returned venue/address data with `serpapi_google_local`,
`serpapi_tripadvisor`, Maps, or weather in a later tool call or workflow step.
See the [focused Google Events guide](../google-events-tool/README.md).

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

### OpenTable Reviews

`serpapi_open_table_reviews` is a focused review lookup, not a restaurant-name
search. Pass either the `r/...` restaurant ID from an OpenTable URL or the full
restaurant URL:

```json
{
  "rid": "https://www.opentable.com/r/central-park-boathouse-new-york-2",
  "page": 1,
  "output_format": "json",
  "max_reviews": 10
}
```

JSON output normalizes the restaurant-wide rating summary, up to ten reviews
from the selected provider page, diner metadata, overall/food/service/ambience/
value/noise ratings, restaurant responses, review photos, and next/previous
page handoffs. Use `output_format: "markdown"` or `"html"` only when the user
explicitly wants the provider-rendered document. Those formats return raw
untrusted content; JSON remains the normal choice for grounded follow-ups and
the Web review-card adapter. If only a restaurant name is known, find its public
OpenTable restaurant URL with a search tool before calling this tool. Its
manifest declares `serpapi_search_index` as a prerequisite, so Tool RAG keeps
that focused URL resolver visible beside the review tool without a hardcoded
OpenTable router rule. Search for the exact restaurant and location on
`opentable.com/r`, verify the matched title/location, and never manufacture an
`r/...` slug from the name.

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

## Shared SerpApi workflows

The shared `data/workflows/serpapi_amazon_search.json` recipe runs
`serpapi_amazon_search`, saves a normalized text export to Stash, and creates a
Canvas comparison report. Its explicit command is:

- `/serpapi_amazon <query>`

The workflow helper model receives only the normalized Amazon rows and has
server-side tools disabled, so it cannot silently replace the deterministic
source step with another search provider.

Seven additional shared recipes combine bounded SerpApi results without crawling
source pages:

- `/buying_brief <product>` compares Google Shopping
  Light, Amazon, and eBay. Google Shopping and Amazon use their existing
  active-mode location/postal defaults; eBay receives
  `JARVIS_DEFAULT_POSTAL_CODE` as a shipping-area bias when configured. The
  workflow makes three normal SerpApi searches, does not fan out into Amazon
  product details, optionally saves a compact Stash snapshot, and creates a
  dated Canvas recommendation.
- `/vacation_reconnaissance <location>` requires an explicit destination and does not fall back
  to Jarvis's configured home location. It combines a seven-day weather
  forecast with Tripadvisor attractions and restaurants, Google Local, Google
  News Light, and Google Images Light. It makes five normal SerpApi searches,
  does not request Tripadvisor enrichment, does not download images, optionally
  saves bounded evidence to Stash, and creates a dated Canvas report.
- `/local_services_compare <service>` uses the active
  mode's configured location to compare five bounded results each from Google
  Local Services, Google Local, and Yelp. Yelp adds up to three review excerpts
  for one selected result. The normal budget is four or five SerpApi searches,
  depending on whether Google Local Services can use a built-in city CID; it
  can be one lower when Yelp returns no selected result for review enrichment.
  The recipe does not crawl provider websites or contact businesses, optionally
  saves bounded evidence to Stash, and creates a dated Canvas shortlist and
  recommendation.
- `/game_brief <sport> <team>` resolves
  the latest game directly, builds a concise score, status, line or period score,
  player-performance, and watch-or-recap report, and publishes it to Canvas.
  Google Sports is required; Brave LLM Context and Brave MCP search are optional,
  and provider-native server-side search remains available to the Canvas helper.
- `/night_out <occasion or preference>` extracts an
  explicitly stated destination or falls back to the active mode's
  `JARVIS_DEFAULT_LOCATION` and then `JARVIS_DEFAULT_POSTAL_CODE`. It combines a
  ten-day weather window with two bounded Google Local searches and optional
  Yelp and destination-anchored Tripadvisor evidence. Canvas preserves the
  requested occasion and date. Weather is an optional conditional step: it is
  skipped before execution when the parsed outing date exceeds the ten-day
  horizon, and current conditions are only a run-time planning snapshot when no
  date is supplied. Provider text such as `Open now` or `Closes in 23 min` is
  likewise treated as run-time-only and never as future-date availability.
  Generic image search is intentionally omitted because unspecific food and
  atmosphere images do not reliably represent a recommended venue.
- `/trend_reality_check <topic>` measures a topic's
  three-month interest curve and related searches, then uses the seedless US
  Trending Now feed, recent Google News Light, and Search Index results as
  optional cross-checks. The report treats Trends values as relative indices,
  not search counts, and absence from Trending Now as weak evidence rather than
  proof that a topic is not trending.
- `/team_outlook <sport> <team>` resolves the team once,
  then uses direct team-games, team-standings, and team-roster calls before
  optionally adding Google News Light storylines. Team standings promote the
  selected team and its division or conference ahead of the general result
  bound, so a late provider-order position is not lost. The Canvas report
  separates the bounded completed-game sample from upcoming games and does not
  infer player availability, playoff odds, or a full-season record from
  incomplete data.

The buying, vacation, local-services, night-out, trend-check, and team-outlook
recipes set `disable_server_side_tools: true`, so their Canvas helper calls can
synthesize only the explicit workflow results. Game Brief deliberately leaves
optional provider-native search available for current recap context while
keeping Google Sports authoritative. All seven remain usable through slash
triggers, the workflow meta-tool, APIs, and scheduled tasks; their required
product, location, service, preference, topic, or sport-and-team input is the
normal workflow query argument.

## Follow-up context and Web UI

Jarvis keeps bounded identifiers from recent SerpApi results so follow-ups can
reuse the correct item or place instead of guessing:

- Amazon ASINs, links, images, prices, ratings, Prime, delivery, and stock;
- eBay and Home Depot product IDs;
- Maps, Yelp, and Tripadvisor place IDs;
- OpenTable restaurant IDs, pagination, rating summaries, and bounded review excerpts;
- Google Trends summaries, regional values, recent timeline points, and
  related links;
- Trending Now volume/growth signals and exact selected-trend news tokens;
- Google Shopping Light product tokens plus Google Immersive Product features,
  review/store context, variant handoffs, and store-pagination tokens;
- Google Images Light full-size image URLs, source pages, dimensions, and
  explicit untrusted-content markers;
- Search Index source URLs and pagination metadata;
- hotel property IDs and stay context;
- Travel Explore destination IDs, airport codes, suggested dates, price
  signals, transfer times, coordinates, and public Google Travel links; and
- YouTube video IDs and URLs.

The Web UI renders structured cards for result types that have dedicated
adapters, including a product-and-store rail for Google Immersive Product.
Links and image URLs remain available to later Stash and Canvas actions.

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
