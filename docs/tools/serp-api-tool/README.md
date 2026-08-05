# SerpApi Search Tool

Use the SerpApi tools to run web, marketplace, maps, and travel lookups through SerpApi from Jarvis.

The base tool is generic by design, and Jarvis now also includes thin SerpApi wrappers for common domains:

- `serpapi_search` for generic engine-based search
- `serpapi_ebay_search` and `serpapi_ebay_product` for eBay discovery and details
- `serpapi_home_depot` for The Home Depot product searches
- `serpapi_maps_search` for Google Maps place and local business lookups
- `serpapi_hotel_search` for Google Hotels searches
- `serpapi_tripadvisor` for Tripadvisor search, place details, nearby suggestions, and reviews
- `serpapi_youtube` for YouTube video detail lookup with transcript fallback
- `serpapi_youtube_search` for YouTube video discovery by keyword
- `serpapi_yelp_search` for Yelp place discovery with attrs and reviews

Future airfare searches use the separate `flight_search` tool. It runs SerpApi
Google Flights when `SERP_API_KEY` is configured and otherwise uses its
keyless fallback; see [the flight search guide](../flight-search-tool/README.md).

## Files

- Shared client: `lib/serpapi_client.py`
- Generic tool: `skills/serpapi_search.py`
- eBay wrappers: `skills/serpapi_ebay_search.py`, `skills/serpapi_ebay_product.py`
- Home Depot wrapper: `skills/serpapi_home_depot.py`
- Maps wrapper: `skills/serpapi_maps_search.py`
- Hotels wrapper: `skills/serpapi_hotel_search.py`
- Tripadvisor wrapper: `skills/serpapi_tripadvisor.py`
- YouTube wrapper: `skills/serpapi_youtube.py`
- YouTube search wrapper: `skills/serpapi_youtube_search.py`
- Yelp wrapper: `skills/serpapi_yelp_search.py`
- Tool definitions:
  - `skills/serpapi_search.tool.json`
  - `skills/serpapi_ebay_search.tool.json`
  - `skills/serpapi_ebay_product.tool.json`
  - `skills/serpapi_home_depot.tool.json`
  - `skills/serpapi_maps_search.tool.json`
  - `skills/serpapi_hotel_search.tool.json`
  - `skills/serpapi_tripadvisor.tool.json`
  - `skills/serpapi_youtube.tool.json`
  - `skills/serpapi_youtube_search.tool.json`
  - `skills/serpapi_yelp_search.tool.json`

## Setup

1. Add your key in env:
   - `SERP_API_KEY` in `config/cloud.env` and/or `config/local.env`
   - Optional: `JARVIS_DEFAULT_POSTAL_CODE` for localized Amazon delivery and Home Depot US availability
2. Sync tools:
   - `./bin/sync-tools.py cloud`
   - `./bin/sync-tools.py local` (if you use local mode)

## Proxy policy

Every shipped SerpApi-backed tool manifest, including `flight_search`,
explicitly defaults to `"proxy_policy": "off"`. Jarvis therefore suppresses
`LOCAL_PROXY`, `LOCAL_PROXY2`, and conventional proxy variables for normal tool
execution even when those values are configured for other tools in the active
mode.

The implementations all keep using the shared proxy-aware SerpApi client. To
opt one tool into the configured proxy chain later, change only its manifest:
`inherit` uses the helper's normal proxy-first behavior, `prefer` explicitly
uses proxy-first with direct fallback, and `require` uses the proxy chain and
fails closed. See [HTTP proxy configuration](../../NETWORK_PROXY.md).

## What it returns

Standard tool contract:

```json
{
  "ok": true,
  "speech": "Found 5 result(s) on 'amazon'...",
  "data": {
    "engine": "amazon",
    "query": "wireless mouse",
    "results_count": 5,
    "results": [
      {
        "title": "...",
        "url": "...",
        "asin": "...",
        "price": "...",
        "rating": 4.6,
        "reviews": 1234,
        "prime_eligible": true,
        "delivery": ["..."],
        "stock": "In Stock"
      }
    ]
  }
}
```

### Incident-aware failures

After a final transient SerpApi failure or tool-process timeout, Jarvis makes one
short, bounded request to SerpApi's public unresolved-incidents JSON endpoint.
If an active incident specifically matches the engine that failed, the error
response includes `data.serpapi_incident`, `failure_reason=active_provider_incident`,
the provider's latest update, its status-page URL, and a recommendation to retry
later. Unrelated incidents do not replace the original tool error, validation
errors do not trigger the lookup, and a failed status lookup is ignored.

## Parameters

| Parameter | Type | Required | Notes |
|---|---|---:|---|
| `engine` | string | yes | Examples: `amazon`, `amazon_product`, `google` |
| `query` | string | no* | Required for most engines |
| `asin` | string | no* | Best for `engine=amazon_product` |
| `amazon_domain` | string | no | Default `amazon.com` |
| `language` | string | no | Default `en_US` |
| `device` | string | no | `desktop`, `mobile`, `tablet` |
| `page` | integer | no | Default `1` |
| `num_results` | integer | no | Clamped to `1..10`, default `5` |
| `delivery_zip` | string | no | Amazon delivery ZIP/postal code; defaults to `JARVIS_DEFAULT_POSTAL_CODE` |
| `shipping_location` | string | no | Optional Amazon shipping country code, such as `US` |
| `include_product_details` | boolean | no | For Amazon search, merge localized product details into the first candidates |
| `product_details_limit` | integer | no | Product-detail enrichments to request (`1..5`, default `5`) |
| `no_cache` | boolean | no | Force fresh fetch |
| `extra_params` | object | no | Pass-through engine params |
| `include_raw` | boolean | no | Include full payload in `data.raw` |

\*Validation rules:
- `amazon_product`: provide `asin` (preferred) or `query`
- other engines: provide `query` or `asin`

## Common usage

### Amazon listing search

```json
{
  "engine": "amazon",
  "query": "gift ideas for 25-year-old tech enthusiast $50-$150 -Apple",
  "num_results": 10
}
```

### Recommended Amazon pattern

For shopping requests, the best flow is usually:

1. Use `engine=amazon` to gather multiple candidate listings.
2. Compare price, rating, reviews, and fit for the request.
3. If the user wants one best item or a deeper look at a chosen candidate, follow with `engine=amazon_product` using the ASIN.

This keeps broad comparison and focused product inspection separate:
- `amazon` is better for candidate discovery and ranking
- `amazon_product` is better for one final item with richer details, direct link, and thumbnail/image

For a bounded comparison that needs reliable Prime, delivery, and stock columns,
set `include_product_details=true`. The tool makes up to
`product_details_limit` localized product calls and deterministically merges
their fields back into the original search rows by ASIN. This avoids handing an
LLM separate discovery/detail payloads and asking it to reconcile them.

Both Amazon engines default `delivery_zip` from `JARVIS_DEFAULT_POSTAL_CODE`.
Normalized results preserve SerpApi's price, rating, reviews, Prime, delivery,
shipping, stock, availability, badge, recent-purchase, and coupon signals when
present. `prime_eligible` is true when SerpApi explicitly marks Prime or its
delivery text explicitly offers a Prime-member delivery option. Missing fields
remain unknown.

Jarvis now also preserves a compact shortlist of prior Amazon candidates in follow-up context, so later turns like:
- `tell me more about the Aura frame`
- `save that one to canvas`
- `show the dog bed again`

can resolve to the right prior ASIN, link, and thumbnail instead of forcing a
fresh guess. When a workflow combines Amazon discovery and product-detail
lookups, the follow-up extractor joins those runs by ASIN and also keeps bounded
price, rating/review, Prime, delivery, shipping, stock/availability, badge,
recent-purchase, and coupon signals.

### Amazon product lookup by ASIN

```json
{
  "engine": "amazon_product",
  "asin": "B072MQ5BRX"
}
```

### Generic search engine example

```json
{
  "engine": "google",
  "query": "best usb c hub 2026",
  "num_results": 5
}
```

### Home Depot product search

```json
{
  "query": "cordless drill",
  "delivery_zip": "97124",
  "sort_by": "top_rated",
  "num_results": 5
}
```

Use this when you want Home Depot product options, store/ZIP-specific availability, or price/rating comparisons. Jarvis preserves a compact shortlist of prior Home Depot candidates in follow-up context so turns like `show me the Milwaukee one` or `save that drill to canvas` can reuse the product ID, link, thumbnail, and price.

For US searches, `delivery_zip` defaults to `JARVIS_DEFAULT_POSTAL_CODE` when omitted. Keep that postal code separate from `JARVIS_DEFAULT_LOCATION` so tools do not need to parse a city/state string.

Home Depot search results include `thumbnail`, `image_url`, and top-level `top_image_url` when SerpApi returns product images. Keep normal searches lightweight: `include_product_details` defaults to false because it makes a second `home_depot_product` request. Use `include_product_details=true` only when the user asks for full product-page details, larger images, bullets, specifications, or similar focused detail.

The `serpapi_home_depot` tool always uses SerpApi's cached responses (`no_cache=false`) and connects directly under the shared default `proxy_policy=off`, which avoids slow proxy timeouts on this engine. Its request path remains proxy-capable if that manifest policy is deliberately changed later. Product `url` / `top_url` values rewrite `apionline.homedepot.com` (SerpApi/API host) to `www.homedepot.com` or `www.homedepot.ca` so links open in a normal browser instead of Akamai "Access Denied".

### Home Depot product details by product ID

```json
{
  "product_id": "341725053"
}
```

Use this when you already have a Home Depot product ID and want the focused product page details, including `image_url`, description, highlights, bullets, specifications, rating, reviews, and price.

### Maps place search

```json
{
  "query": "coffee shops in Austin",
  "hl": "en",
  "num_results": 5
}
```

### Hotel search

Use `serpapi_hotel_search` for future stays with date-specific Google Hotels
prices. It requires `SERP_API_KEY`, makes one SerpApi search, and connects
directly under the shared `proxy_policy=off` default.

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

The routing contract expects explicit `YYYY-MM-DD` dates. Jarvis resolves
phrases such as "next Tuesday" from the runtime-injected current date before it
calls the tool. For "hotels near me," it may use the injected
`JARVIS_DEFAULT_LOCATION`; a location named by the user always wins.

The default `sort_by` is `price`. The tool asks Google Hotels for lowest-price
results, normalizes the whole returned property page, locally sorts by the
lowest listed total for the complete stay, and only then applies `num_results`.
This avoids treating Google's relevance order—or small inconsistencies in the
provider's price order—as a verified cheapest-first list. Other supported sorts
are `rating`, `reviews`, and `relevance`.

Each response identifies the stay dates, number of nights, guests, currency,
returned/property counts, and SerpApi search count. Hotel rows preserve an
opaque `property_id`, property or booking URL when available, nightly and total
prices, before-tax prices, rating/review counts, star class, amenities,
cancellation signal, thumbnail, and compact nearby-place/booking options.
Properties that SerpApi reports only under `non_matching_properties` are not
presented as matches for active filters.

If child ages are supplied, their count must match `children` and every age must
be 1 through 17. Ages remain optional because SerpApi also accepts a children
count without them. Date order, past dates, guest counts, currency, rating,
class, price range, device, and integer filter IDs are validated before any
billable request.

Prices are reference quotes and can change. The tool never reserves a room or
submits payment; use the returned property/provider link to review restrictions
and book manually. `no_cache` defaults to false so identical searches can use
SerpApi's cache. Set it only for an explicit fresh refresh. `include_raw` is a
debug option and is off by default.

### YouTube video details with transcript fallback

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "include_transcript": true,
  "language_code": "en"
}
```

Use this when `yt-dlp`-based tools fail because of cookies, auth, or transcript availability issues but you still want structured video details and any transcript SerpApi can expose.

### YouTube search

```json
{
  "search_query": "pepper fermenting hot sauce",
  "num_results": 5
}
```

Use this when you want to find candidate YouTube videos first, then pass the chosen URL into `serpapi_youtube`, `youtube_transcript`, or `youtube_video`.

### Yelp search with local ranking, filters, and optional reviews

```json
{
  "find_desc": "Coffee",
  "find_loc": "New York, NY, USA",
  "dogs_allowed": true,
  "sort_by": "rating",
  "include_reviews": true
}
```

Use this when you want restaurants, coffee shops, or other Yelp places near a
location, especially when Yelp ratings, review counts, price tiers, or attrs
like `DogsAllowed` and `GoodForKids` matter. A normal lookup uses one SerpApi
request. `include_reviews` makes one additional paid request for the supplied
`place_id` or the top returned result, so enable it only when review excerpts
are actually needed.

The default preserves Yelp's recommended order. `rating` and `review_count`
sort the complete returned page locally; this avoids a current Yelp response
variant where explicitly sorted requests omit names and ratings. The tool
returns Yelp URLs and place IDs plus ratings, review counts, price tiers,
categories, neighborhoods, open-state labels, and snippets when available.
Yelp search results do not consistently include street addresses or full hours,
so use `serpapi_maps_search` or a generic web search when those exact details are
required.

## How to prompt Jarvis

Natural prompt:

`Hey Jarvis, find 5 Amazon gift ideas for a 25-year-old tech enthusiast, budget $50-$150, avoid Apple accessories, include links and why each is good.`

Tool-forced follow-up:

`Use serpapi_search with the same query and return 5 options with links.`

Focused follow-up:

`Take the best ASIN from those options, use serpapi_search with engine=amazon_product, and give me the direct product details and link.`

## Known behavior and troubleshooting

### "It used Brave MCP instead"

Tool choice is a routing decision. If you need this tool specifically, ask explicitly:

`Use serpapi_search for this query.`

### "It called tools too many times"

This is usually orchestration loop behavior, not a SerpApi request failure.

In recent testing, repeated calls were caused by follow-up canvas actions after a failed canvas update, while `serpapi_search` itself returned `ok: true`.

### First-turn error

If first call fails, check:

- `SERP_API_KEY` exists and is not a placeholder
- proxy/network path is healthy (`LOCAL_PROXY` / `LOCAL_PROXY2`: see [`docs/NETWORK_PROXY.md`](../../NETWORK_PROXY.md))
- `logs/tools/tool-calls-YYYY-MM-DD.jsonl` for exact failing tool

### Results not matching budget

Amazon search quality depends on query wording. Add stronger constraints:

- include budget in query (`$50-$150`)
- exclude brand terms (`-Apple`)
- use `extra_params` for engine-specific filters when needed

## Notes

- Links in `data.results[].url` can be rendered in WebUI and shown in CLI output.
- For focused Amazon product lookups, Jarvis WebUI can now render a single product preview card with image, title, price, rating, reviews, ASIN, and direct link when the tool returns one clear item.
- If a focused Amazon product result is later saved to Canvas, the thumbnail/image URL can now be embedded on the page instead of only appearing as plain text.
- For cleaner gift recommendations, pair this tool with one synthesis step that filters out low-quality matches.
