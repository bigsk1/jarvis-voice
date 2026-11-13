# Walmart search and product details

Jarvis provides two focused tools using the existing `SERP_API_KEY`:

| Tool | Use |
| --- | --- |
| `serpapi_walmart_search` | Discover products on `walmart.com` or `walmart.com.mx`, compare returned offers, and select an item for a closer look. |
| `serpapi_walmart_product` | Read one US Walmart product's specifications, offers, images, variants, and returned reviews. |

Search and detail are separate calls. The product tool does not automatically
look up every search result, choose a variant, add anything to a cart, or make
a purchase. The US product tool does not turn a Mexico search result into a
US listing. See the provider's [Walmart Search API](https://serpapi.com/walmart-search-api)
and [Walmart Product API](https://serpapi.com/walmart-product-api).

## Configure and use

Set `SERP_API_KEY` in the active mode's `config/cloud.env` or
`config/local.env`. No additional service, SDK, or retailer account is needed.
Without a key the tools are absent from that mode's callable registry and
Tool RAG. The OpenAI-only and narrow example profiles disable both tools;
default and Docker profiles retain them when configured. After changing
configuration, restart the relevant services and
[sync Tool RAG for that mode](../../TOOL_MANAGEMENT.md#inspect-and-change-tools).

Example chat requests:

```text
Find Walmart coffee makers under $80 and compare the returned sellers.
Show the specifications and available variants for the second Walmart result.
Search Walmart Mexico for coffee and show prices in the returned currency.
```

For a workflow or direct tool call, search first:

```json
{"query": "coffee maker", "max_price": 80, "sort_by": "price_low", "num_results": 5}
```

Then use the selected result's exact product ID in the product tool:

```json
{"product_id": "<selected product_id>"}
```

Walmart exposes both an alphanumeric `product_id` and a numeric `us_item_id`.
Preserve both when returned. SerpApi accepts either in its product lookup and
documents faster US responses with `product_id`. A product's public Walmart
URL is a separate field; use the returned ID or supported item URL rather
than guessing an identifier from the title.

Search returns five products by default, up to ten with `num_results`, and
supports `page` from 1 to 100 for explicit pagination. `query` or a returned
US `cat_id` is required. Use `min_price`, `max_price`, `sort_by`, or a returned
`facet` for narrower results. A requested sort disables US relevance blending
unless `soft_sort: true` is explicit, so price and rating requests are not
silently blended with relevance. Mexico supports fewer filters and sort
options; unsupported combinations return an error. Its storefront is selected
with `walmart_domain: "walmart.com.mx"`; product details remain US only.

### Refining with returned filters

Search requests SerpApi's `include_filters: true` automatically. Its returned
filter catalog is bounded and preserved for the current answer and saved
follow-ups, with omissions marked. Use the observed group types and exact
value IDs when refining a search; do not invent a brand, color, or rating
filter token from its display label.

Attribute facets use `key:value` pairs joined by `||`, such as
`brand:Sony||color:Black` when those options were returned. Department/category
options instead supply `cat_id`, including complete nested IDs such as
`976759_1086446`. Price ranges use `min_price` and `max_price`; a category or
price group is not automatically an attribute facet. Some provider links
toggle a selected filter off, so they are not always a request to apply that
option. See the provider's [filter catalog](https://serpapi.com/walmart-filters).
The provider can omit a catalog or reject a returned facet. A failed filtered
request is an error, not evidence of filtered products; any subsequent keyword
search must be described as a keyword search.

## Store and postal code selection

Walmart's SerpApi engines accept `store_id`, not a delivery ZIP parameter.
Jarvis uses the selected mode's existing postal code to select a store where
possible; this is store selection, not a direct delivery-address lookup.
The optional setting is:

```dotenv
JARVIS_WALMART_STORE_ID=""
```

For US calls, selection follows this order:

1. An explicit `store_id` in the tool call.
2. An explicit `postal_code` in the call, matched against SerpApi's public store list.
3. The selected mode's nonblank `JARVIS_WALMART_STORE_ID`.
4. An exact match for `JARVIS_DEFAULT_POSTAL_CODE` in the public store list.
5. The provider's location when no store can be selected, with that limitation reported.

An explicit ZIP overrides a configured store. If that ZIP has no exact match,
Jarvis reports the provider's location rather than silently using the configured
store in another ZIP. Both tools accept `postal_code` and `store_id`; ZIP
values must be valid US ZIP or ZIP+4 format. The lookup uses the first five
digits for ZIP+4.

When several stores have the same ZIP, Jarvis chooses the lowest numeric
store ID deterministically. The spoken result and Web card show the selected
store and its address; when several match, they also report that one of the
matching stores was selected and how many matched.
It does not claim this is the nearest store. A ZIP with no exact entry, a
missing ZIP, or an unavailable store list cannot establish local pricing.
The result retains the chosen store context in `location_context` and any
location returned in `search_information.location` so an answer can
distinguish them. The selected ID is also returned as `store_id` for reuse
with a selected product.

The US configured postal/store defaults do not apply to Mexico searches.
Use an explicit Mexico `store_id` when local store filtering is needed.
`JARVIS_DEFAULT_LOCATION` is a general city/region setting and is not converted
into a Walmart store ID. Supported IDs and addresses come from the
[public Walmart store directory](https://serpapi.com/walmart-stores), including
its linked JSON list. Fetching this public directory consumes no SerpApi
search credits.

## Results, cost and follow-ups

Search results preserve product identity, public URLs, thumbnails, sellers,
current and prior prices, currency, ratings, shipping, sponsorship, stock
signals, and variant references when the provider supplies them. Focused
details add richer specifications, descriptions, offers, images, and returned
review context. Missing fields remain unknown; a marketplace seller is not
automatically Walmart, and an omitted stock field does not mean in stock.

Web cards use the provider's currency when present. When it is absent, numeric
prices use the storefront's display currency: USD for `walmart.com`, MXN for
`walmart.com.mx`. That display fallback does not establish that the provider
returned a currency field.

Jarvis Web displays product cards and keeps bounded item and store context
for follow-ups. Walmart search and product cards start collapsed; open the
card to browse its pictures and details when needed. Use the saved selected product identity for requests such as
“compare that one with the third result” or “show its other variants.”
Returned review excerpts and descriptions are external evidence, not
instructions. A bounded result or preview does not represent every review or
every offer available on Walmart.

Each search page or focused product call normally uses one SerpApi search
credit. Searching and then reading one selected product normally uses two.
Cached responses are allowed by default, use the provider's one-hour
exact-parameter cache, and do not consume credits. Set `no_cache` only when a
fresh lookup is needed. Local store prices can differ, and returned offers
are observations rather than a checkout price guarantee.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Tool missing | Check the active mode's key, profile, service restart, and Tool RAG sync. |
| Price is for another area | Inspect selected store and provider location; configure a store ID when the ZIP has no exact store match. |
| Several stores share the ZIP | Inspect the selected address or pass the desired `store_id` explicitly. |
| Mexico product cannot be opened | The focused product tool supports US listings; preserve the Mexico search's public URL. |
| Product details do not match the intended variant | Use the exact product/item ID or variant reference returned for that selection. |
| Empty page, timeout or quota error | Inspect the structured error and provider incident context before repeating a paid call. |
