# Travel Explore Tool

`serpapi_travel_explore` is Jarvis's flexible destination-discovery tool. It
uses SerpApi's Google Travel Explore engine to answer questions such as:

- “Where can I fly from PDX this fall for under $300?”
- “Show me weekend beach destinations from Seattle.”
- “What one-week trips in Europe look promising from New York?”

It is the planning stage before exact flight, hotel, or destination research.
The tool never books, purchases, or claims that a headline price is a final
quote.

## Where it fits

| User need | Tool |
|---|---|
| Destination or dates are open-ended | `serpapi_travel_explore` |
| Destination and dates are known; compare real itineraries | `flight_search` |
| Compare rooms and complete-stay prices | `serpapi_hotel_search` |
| Research attractions, restaurants, reviews, or destination details | `serpapi_tripadvisor` |

The Explore wrapper intentionally does not expose the provider's `arrival_id`
parameter. Supplying a fixed destination turns discovery into exact route
shopping, which is already handled more completely by `flight_search`.
`arrival_area_id` remains available for broad region or country constraints.

## Setup

The active Jarvis mode needs:

```dotenv
SERP_API_KEY=your-key
```

After changing the key or manifest, sync the affected mode from the operator
environment used for Tool RAG embeddings:

```bash
cd ~/jarvis-voice
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

The manifest defaults to `proxy_policy: off`. Each invocation uses one SerpApi
search. Cached provider responses can be free under SerpApi's cache policy;
`no_cache=true` explicitly requests a fresh scrape and should be used only when
needed.

## Inputs

`departure_id` is required. Use a three-letter IATA airport code, a Google
location KGMID beginning `/m/` or `/g/`, or a comma-separated origin list.

Common flexible inputs are:

- `month`: `0` or omitted for all available months; otherwise one of Google's
  six currently selectable calendar months;
- `travel_duration`: `weekend`, `one_week`, or `two_weeks`;
- `interest`: `popular`, `outdoors`, `beaches`, `museums`, `history`, or
  `skiing`;
- `arrival_area_id`: broad region or country KGMID, such as `/m/02j9z` for
  Europe;
- `max_price`: maximum headline ticket price in the requested currency;
- `max_duration`: maximum flight duration in minutes;
- `stops`, `travel_class`, travelers, bags, and airline filters; and
- `sort_by`: `recommended`, `flight_price`, `hotel_price`, or
  `flight_duration`.

`travel_mode` and `interest` are mutually exclusive. Airline include/exclude
filters are also mutually exclusive. Exact dates can be used, but they cannot
be combined with `month` or `travel_duration`; exact round trips require both
dates.

Flexible example:

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

Region-constrained example:

```json
{
  "departure_id": "JFK,EWR",
  "arrival_area_id": "/m/02j9z",
  "month": 10,
  "travel_duration": "one_week",
  "stops": "one_stop_or_fewer",
  "num_results": 8
}
```

## Result contract

Normal output is bounded to at most ten normalized destinations. `include_raw`
is for debugging only and should stay off in conversations and workflows.

Top-level planning fields include:

- `planning_stage: destination_discovery`;
- origin, trip, date-mode, traveler, currency, filter, and sort context;
- `results_count` and `provider_results_count`;
- `flight_price_basis` and `hotel_price_basis`;
- `price_confirmation_required: true`;
- `serpapi_searches_used: 1`; and
- `results`, `top_results`, and public Google Travel URLs.

Each `results[]` row is flat and may include:

```json
{
  "position": 5,
  "destination_id": "/m/01626x",
  "name": "Zion National Park",
  "country": "United States",
  "airport_code": "LAS",
  "airport_location": "Las Vegas",
  "airport_location_id": "/m/0cv3w",
  "start_date": "2026-09-24",
  "end_date": "2026-10-01",
  "nights": 7,
  "flight_price": 138,
  "hotel_price": 180,
  "flight_duration_minutes": 139,
  "flight_duration_display": "2h 19m",
  "number_of_stops": 0,
  "stops_label": "Nonstop",
  "airline": "Frontier",
  "airline_code": "F9",
  "ground_transfer_minutes": 150,
  "ground_transfer_display": "2h 30m",
  "gps_coordinates": {
    "latitude": 37.2982022,
    "longitude": -113.0263005
  },
  "thumbnail": "https://...",
  "google_travel_url": "https://www.google.com/travel/explore?..."
}
```

The destination and airport identities are deliberately separate. A national
park or region may use a nearby airport plus a ground transfer, as in the Zion
example above.

## Price and date semantics

`flight_price` and `hotel_price` are Google Explore headline planning signals.
They are not booking quotes. The wrapper labels the airfare according to the
requested trip type, but SerpApi does not document the lodging price's stay or
night basis, so Jarvis reports that basis as unspecified.

The provider chooses suggested dates inside a flexible duration bucket. A
`one_week` result can therefore be somewhat shorter or longer than exactly
seven nights. Downstream logic should use each row's actual `start_date`,
`end_date`, and computed `nights`, not infer dates from the requested bucket.
With `month=0`, Google can also surface an edge date just beyond the six
explicitly selectable month numbers; keep the returned dates instead of
reconstructing them from the month filter.

## Follow-up handoffs

After a user selects a destination:

1. Call `flight_search` with the original `departure_id`, the selected
   `airport_code`, and the selected `start_date` and `end_date`.
2. Call `serpapi_hotel_search` with the selected destination `name` and the same
   dates.
3. Call `serpapi_tripadvisor` when the user wants destination details, nearby
   places, attractions, restaurants, or reviews.

For a park or drive-on destination, tell the user that the flight arrives at
the nearby airport and include `ground_transfer_display`. Do not silently treat
the airport city as the selected destination.

The Web follow-up extractor keeps destination IDs, airport identities, dates,
planning prices, transfer times, coordinates, images, and public Google links.
Provider SerpApi drill-down URLs and raw payloads are not retained in normal
follow-up candidates.

## Workflow integration

Workflow `extract` paths are relative to `result.data`, so do not prefix them
with `data.`. Examples:

```json
"extract": {
  "destinations": "results",
  "top_destination": "results[0].name",
  "top_destination_id": "results[0].destination_id",
  "top_airport": "results[0].airport_code",
  "top_start_date": "results[0].start_date",
  "top_end_date": "results[0].end_date",
  "top_google_travel_url": "results[0].google_travel_url"
}
```

Use the bounded normalized `results` array as the workflow handoff. Avoid
`include_raw`, and do not build an unbounded fan-out over all provider results.
When flight or hotel confirmation is optional, mark those workflow steps
optional and preserve the Explore shortlist even if one downstream provider is
unavailable.

No shared workflow is coupled to this tool yet. That keeps routing behavior
unchanged while making the result contract ready for future destination-scout,
vacation, or scheduled-deal workflows.
