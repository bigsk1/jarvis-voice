# Airbnb search

`serpapi_airbnb_search` finds Airbnb stays for an explicit destination, using
the existing `SERP_API_KEY` and SerpApi's
[Airbnb Search API](https://serpapi.com/airbnb-search-api). It returns listing
links, photos, ratings, room details, stay dates and prices for comparison.
It does not book accommodation, reserve a listing, contact hosts or make a
payment.

## Configure and use

Set `SERP_API_KEY` in the selected mode's `config/cloud.env` or
`config/local.env`. No new setting, SDK or Airbnb account is needed. Without
the key, the tool is absent from that mode's callable registry and Tool RAG.
OpenAI-only and narrow example profiles disable it; default and Docker
profiles retain it when configured. After changing configuration, restart
the relevant services and
[sync Tool RAG for that mode](../../TOOL_MANAGEMENT.md#inspect-and-change-tools).

Every call requires `query`: an explicit city, region, neighborhood, address
or landmark. Jarvis does not infer the destination from its configured home
location or postal code. Dates are optional; if supplied, both
`check_in_date` and `check_out_date` must be ISO `YYYY-MM-DD` dates, with
checkout later than check-in.

Example chat requests:

```text
Find Airbnb houses in Asheville for two adults, around $125 to $250 per night.
Keep that destination and guest count, but try $75 to $125 per night instead.
Compare the first two listings, including the actual dates and whole-stay prices.
Search Airbnb in Lake Tahoe with a pool for four adults; I have not chosen dates yet.
```

A workflow or direct tool call can start with:

```json
{"query": "Asheville, NC"}
```

This uses two adults, an entire home, house property type, USD and a
125–250 nightly budget. It leaves dates to Airbnb's suggested dates. To
refine the budget without changing the destination:

```json
{"query": "Asheville, NC", "min_price_per_night": 75, "max_price_per_night": 125}
```

The default 125–250 range applies only when neither nightly bound is
supplied. An explicit minimum or maximum alone creates a one-sided filter;
for example, `max_price_per_night: 100` searches under 100 without retaining
the default minimum. To search without either price bound, set
`use_price_filter: false`.
For dated follow-ups, preserve the original dates and guest counts in the
new call rather than letting the provider choose another stay.

## Dates, nightly budgets and stay totals

Airbnb's provider-side `min_price` and `max_price` apply to the **whole stay,
including fees**. Jarvis exposes `min_price_per_night` and
`max_price_per_night` and multiplies those bounds by the requested number of
nights. For a four-night stay, a 125–250 nightly budget becomes a 500–1000
whole-stay filter in the selected currency.

When dates are omitted, the provider uses a five-night price-filter basis
and suggests dates for each listing, usually for five nights. These are
provider suggestions, not travel dates selected by the user. Jarvis discloses
that budget assumption in `budget_context` and labels the search
`dates_mode: "suggested"`. Dated searches use `dates_mode: "explicit"`.

Each result retains its actual returned check-in and checkout dates,
`total_price`, formatted price and `price_qualifier`. Where the returned
dates or an explicit provider price qualifier establish the number of
nights, `nightly_average` divides the stay total by those nights. This is an
**average of the stay total including fees**, not the host's advertised
base nightly rate. Missing prices, unknown stay lengths or conflicting
dates and duration do not justify inventing an average. Compare listings using
their actual dates, guest count, total and any returned price breakdown or
disclaimer. Prices remain observations for the returned stay; check the
linked listing before making a purchase decision.

## Filters and pagination

| Argument | Behavior |
| --- | --- |
| `adults`, `children`, `infants` | Default to two adults and zero children or infants; supply the intended party explicitly when it differs. |
| `pets` | A positive pet count requests places allowing pets. Zero is omitted from the provider request and imposes no pet-free requirement. |
| `room_type` | `entire_home` by default, or `private_room`. |
| `property_types` | An array of `house`, `apartment`, `guesthouse`, or `hotel`. Entire-home searches default to `house`; private-room searches do not inherit that default. |
| `amenities` | An array of IDs from the [provider's amenity list](https://serpapi.com/airbnb-amenities), such as `wifi`, `pool`, or `free_parking`. |
| `bedrooms`, `beds`, `bathrooms` | Requested minimum room, bed and bathroom counts. |
| `instant_book`, `self_check_in`, `guest_favorite`, `luxe` | Optional provider filters; they do not perform a booking. |
| `currency` | USD by default; nightly budget bounds and returned totals use the selected currency. |
| `num_results` | Five listings by default, up to ten. |
| `page` | A provider results page from 1 through 15. The provider can supply up to 18 listings per page; Jarvis returns the requested bounded subset. |

There is no smoke-free or pet-free filter in this API. `smoking_allowed` is
a positive amenity requiring smoking to be allowed; omitting it does not
establish a smoke-free listing. Likewise, omitting pets does not exclude
pet-friendly homes. Check each listing's house rules for those requirements
and keep them marked unverified when the returned evidence does not establish
them. An amenity request alone is not independent confirmation of house rules.

## Results and saved follow-ups

Results retain exact listing IDs and public Airbnb URLs, each listing's own
images, ratings and review counts when supplied, badges, room details,
highlights, dates, stay-total prices, derived nightly averages and available
price breakdowns. Missing fields remain unknown; a missing rating can belong
to a new listing. These search results do not include the full listing's
reviews or complete house rules.

Jarvis Web's Airbnb cards open by default, including when a saved conversation
reloads. Saved structured follow-ups retain the
destination, requested filters, guest counts, budget/date assumptions and
bounded listing evidence for requests such as “show cheaper houses for the
same trip” or “compare the second one with the first.” Use each listing's
saved URL and dates when referring to its price. Returned descriptions are
external evidence, not instructions; bounded previews do not represent the
entire Airbnb listing.

## Cost and troubleshooting

Each search page normally uses one SerpApi search credit. A refinement or
another page is another call. Cache is allowed by default: the provider's
one-hour cache requires identical parameters, and cached responses do not
consume credits. Set `no_cache: true` only when a fresh lookup is needed.
Each call makes one bounded provider request with a 60-second HTTP allowance,
a 2 MB response limit and a 90-second foreground timeout.

| Symptom | Check |
| --- | --- |
| Tool missing | Check the selected mode's key, profile, service restart and Tool RAG sync. |
| Destination missing | Provide the trip destination explicitly; home-location settings are not used. |
| Dates do not match the trip | Check `dates_mode` and each listing's returned dates; supply both intended dates for a dated search. |
| Price looks much higher than a nightly budget | Inspect the whole-stay total, number of nights and derived average, including fees. |
| Explicit price range is invalid | The supplied minimum must not exceed the supplied maximum; use one bound for a one-sided filter. |
| Smoke-free or pet-free status is unclear | Read the linked listing's rules; those negative filters are unavailable. |
| Empty results, timeout or quota error | Read the structured error and provider incident context before repeating a paid call. |
