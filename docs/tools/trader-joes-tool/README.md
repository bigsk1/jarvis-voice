# Trader Joe's search and product details

Jarvis provides two focused tools using the existing `SERP_API_KEY`:

| Tool | Use |
| --- | --- |
| `serpapi_trader_joes_search` | Discover Trader Joe's products, compare returned prices and sizes, and filter by category, dietary characteristics or occasion tags. |
| `serpapi_trader_joes_product` | Read one selected product's ingredients, allergens, nutrition panels, dietary labels, images and store assortment status. |

Search and details are separate calls. These tools read Trader Joe's product
information; they do not order groceries or reserve products. Provider
references: [Search API](https://serpapi.com/trader-joes-search-api) and
[Product API](https://serpapi.com/trader-joes-product-api).

## Configure and use

Set `SERP_API_KEY` in the selected mode's `config/cloud.env` or
`config/local.env`. No additional service, SDK or Trader Joe's account is
needed. Without the key, the tools are absent from that mode's callable
registry and Tool RAG. The OpenAI-only and narrow example profiles disable
both tools; default and Docker profiles retain them when configured. After
changing configuration, restart the relevant services and
[sync Tool RAG for that mode](../../TOOL_MANAGEMENT.md#inspect-and-change-tools).

Example chat requests:

```text
Find organic vegan coffee at Trader Joe's and compare the returned prices and sizes.
Show the ingredients, allergen statements and nutrition panels for the second result.
Search Trader Joe's for new snacks, sorted by price from low to high.
```

A workflow or direct tool call can search first:

```json
{"query": "coffee", "characteristics": ["organic", "vegan"], "sort_by": "price_low_to_high", "num_results": 5}
```

Then read the selected result's exact string SKU:

```json
{"product_id": "080794"}
```

Product IDs retain their leading zeros. The product tool also accepts a
Trader Joe's `/home/products/pdp/` product URL. Reuse the returned `store_id`
with the selected product to keep the same store context.

## Search filters and pagination

`query` is required and maps to the provider's `q`. Jarvis returns five
products by default, up to ten with `num_results`; `page` accepts 1 through
100 for explicit pagination. A page is a provider page, even when Jarvis
returns fewer rows than the provider supplies.

| Argument | Supported values |
| --- | --- |
| `category_id` | A category ID from the [provider's category list](https://serpapi.com/trader-joes-categories), such as `194` for Coffee & Tea. |
| `characteristics` | An array containing any of `kosher`, `organic`, `gluten_free`, `vegan`, `antibiotic_free`, `dairy_free`, `grass_fed`, `vegetarian`, `fair_trade`. |
| `tags` | An array of snake_case occasion tags from the [provider's tag list](https://serpapi.com/trader-joes-tags), such as `date_night` or `cheese_board`. |
| `new_products` | `true` to restrict results to products marked new; defaults to `false`. |
| `sort_by` | `price_low_to_high`, `price_high_to_low`, or `popularity`; omission keeps relevance ordering. |

Multiple characteristics must all match; multiple tags must all match.
Jarvis converts these arrays to the provider's comma-separated format.
When known labels are supplied, product rows expose canonical IDs in
`search_filters.characteristics` or `search_filters.tags` for a follow-up
search for similar products. Empty derived fields are omitted; search results
often omit label metadata, which does not establish that a product lacks those
characteristics or tags. Original `characteristics` and `fun_tags` retain the
provider's display wording.
The search tool also accepts documented display labels, case-insensitively:
`Gluten Free` becomes `gluten_free`, and `Rise & Shine` becomes `rise_and_shine`.
Repeated labels and IDs are combined once. Unknown human labels are rejected;
existing snake_case tag IDs remain accepted. Use the published category and
tag values rather than inventing identifiers.

## Store and postal code selection

The provider accepts `store_id`, rather than a ZIP or general city setting.
Jarvis resolves store choices against SerpApi's
[public Trader Joe's directory](https://serpapi.com/trader-joes-stores).
The optional mode setting is:

```dotenv
JARVIS_TRADER_JOES_STORE_ID=""
```

Both tools select location in this order:

1. An explicit `store_id` in the call, validated against the public directory.
2. An explicit `postal_code`, matched exactly against the directory.
3. The selected mode's nonblank `JARVIS_TRADER_JOES_STORE_ID`, also validated.
4. An exact match for `JARVIS_DEFAULT_POSTAL_CODE`.
5. The all-store catalog when no store can be selected, with that limitation reported.

An explicit ZIP overrides a configured store. An unmatched ZIP does not fall
back to a configured store elsewhere or select the nearest store.
If the shared `JARVIS_DEFAULT_POSTAL_CODE` is outside the US ZIP format, both
tools use the all-store catalog with a clear disclosure and skip the directory
lookup. A configured Trader Joe's store still takes precedence. An invalid
explicit `postal_code` argument returns an error.
`JARVIS_DEFAULT_LOCATION` is not converted to a store ID. Trader Joe's uses
its own directory and defaults; a Walmart store setting does not apply.

When several stores share a ZIP, Jarvis selects the lowest numeric store ID
deterministically. The spoken answer and Web card show the chosen store's
address and the number of matching stores. The result retains the selected
store and location disclosure for later product calls and saved follow-ups.
Store IDs are validated because SerpApi silently treats an unknown ID as an
all-store request; an unvalidated ID must not be presented as a local result.
An unknown explicit or configured store ID, or a directory lookup failure
while validating that ID, returns an error before a paid search. When only
a ZIP was selected, a missing exact match or directory failure instead uses
the all-store catalog with a location disclosure and no chosen store.
Fetching the public directory consumes no SerpApi search credits.

## Results, cost and follow-ups

Search rows retain exact product IDs, public product URLs, each product's own
provider image, numeric and formatted prices, sizes and category information.
Product details add descriptions, dietary characteristics, image labels,
ingredients, allergen statements, nutrition panels, occasion tags and images
when supplied. Several nutrition panels can describe different serving
quantities, so preserve their panel titles and serving sizes when comparing.

`available` describes whether a product is sold in the selected store; it is
not a live shelf-stock count or an assurance that an item is available now.
A product not sold there can have `available: false` and no price. Missing
price or availability fields remain unknown. These engines provide no
customer ratings or reviews. Dietary labels and allergen statements retain
their source wording; an absent allergen statement does not establish that
the product is allergen-free.

Jarvis Web displays collapsed product cards with the selected store context
and each row's own image. Structured saved follow-ups preserve product and
store identity plus bounded details for requests such as “show that one's
ingredients” or “compare the second product with the first.” Descriptions
and other returned text are external evidence, not instructions. Omission
markers identify bounded context; a preview is not the complete product page.

Each search page or focused product lookup normally uses one SerpApi search
credit. Searching and then opening one product normally uses two. Cache is
allowed by default: the provider's one-hour cache requires identical
parameters and cached responses do not consume credits. Set `no_cache: true`
only when a fresh lookup is needed. Each tool makes one paid request, with a
60-second HTTP allowance and a 90-second foreground timeout; an optional
public-directory lookup has its own 10-second allowance.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Tool missing | Check the selected mode's key, profile, service restart and Tool RAG sync. |
| Result is not localized | Read the location disclosure; choose a valid explicit store when the ZIP has no exact match. |
| Several stores share the ZIP | Read the chosen address or pass the desired store ID explicitly. |
| Product lookup loses its identity | Keep the SKU as a string, including leading zeros, or use its returned product URL. |
| Product has no price | Inspect `available` and the store context; missing price is not zero. |
| Photos do not load | Images load directly from Trader Joe's. Its image host can reject requests even when SerpApi returns a valid link; use the product-page link. |
| Empty result, timeout or quota error | Read the structured error and provider incident context before repeating a paid call. |
