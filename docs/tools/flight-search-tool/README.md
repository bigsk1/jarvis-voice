# Flight Search Tool

`flight_search` returns real flight options — prices, departure and arrival times, airlines, stops, and layovers — for a route and date. It is a research tool: it never books or pays for anything, and every result carries a Google Flights link so the booking can be finished manually.

Ask for it the way you would say it out loud:

> "Find me a flight from PDX to PHX leaving September 15th, back on the 20th."

## Files

- Tool: `skills/flight_search.py`
- Definition: `skills/flight_search.tool.json`
- Shared result normalization: `lib/serpapi_client.py` (`extract_flight_results`, `extract_price_insights`)
- Tests: `tests/test_flight_search.py`

## Providers

The provider is chosen automatically at call time. There is no configuration switch and no new environment variable.

| Condition | Provider | Notes |
|---|---|---|
| `SERP_API_KEY` is set | SerpApi `google_flights` | Full fidelity: flight numbers, legroom, delay history, price insights, and every filter. Costs one SerpApi search per call. |
| `SERP_API_KEY` is unset | `fast-flights` | Keyless reader for Google Flights. Free, but Google rejects a minority of queries outright and returns no flight numbers. |

The response reports which one ran in `data.provider`, and `data.serpapi_searches_used` records the quota cost (`1` for SerpApi, `0` for the fallback).

### Fallback limitations

`fast-flights` encodes only the route, date, cabin, passengers, and maximum stops into its query. Anything else is either applied locally after the fact (`max_price`, `include_airlines`) or not applied at all. Filters that could not be honored are listed in `data.unapplied_filters` so the model does not claim a filter was used when it wasn't.

Google intermittently refuses these keyless queries and returns no data for a given date, which surfaces as a clear error rather than an empty result. Retrying does not reliably help. If flight search matters, set `SERP_API_KEY`.

## Round trips

Supplying `return_date` makes the search a round trip. That is a **single request** to the provider, matching how Google itself prices a round trip: one total fare covering both legs, listed against the outbound options.

This means `data.results[].price` is the whole round-trip fare (`data.price_basis` is `round_trip_total`), and the itineraries show outbound times. Choosing a specific return leg happens on the Google Flights site via `data.booking_url`.

Omit `return_date` for a one-way search.

## Defaults

- **Sort:** cheapest first. `sort_by` defaults to `price`; pass `duration` for fastest or `top_flights` for Google's balanced picks.
- **Cabin:** `economy`.
- **Stops:** `any`. Pass `nonstop` when the user asks for direct flights.
- **Travelers:** 1 adult. Google caps a single search at 9 travelers and requires one adult per lap infant; both rules are enforced before the request goes out.
- **Results:** 5, capped at 10.
- **Currency:** `USD`.

## Dates

Dates are `YYYY-MM-DD`. Relative phrasing like "next Friday" is resolved by the model against the current date, which the router already injects into the system prompt.

Past dates are rejected against the configured application timezone (`JARVIS_TIMEZONE`, via `lib/time_utils.now_local`) with a message asking for the intended year, which is the common failure when a month and day are given without one.

## Example

```bash
./skills/flight_search.py '{"departure_id":"PDX","arrival_id":"PHX","outbound_date":"2026-09-15","return_date":"2026-09-20","stops":"nonstop"}'
```

```json
{
  "ok": true,
  "speech": "Found 5 round trip option(s) from PDX to PHX. Best price is $257 on Alaska, Nonstop, 2h 48m, departing 7:03 AM on Tue Sep 15.",
  "data": {
    "provider": "serpapi",
    "trip_type": "round_trip",
    "price_basis": "round_trip_total",
    "cheapest_price": 257,
    "results": [
      {
        "price": 257,
        "airlines": ["Alaska"],
        "flight_numbers": ["AS 1234"],
        "departure_time": "2026-09-15 07:03",
        "arrival_time": "2026-09-15 09:51",
        "duration_display": "2h 48m",
        "stops_label": "Nonstop",
        "layovers": [],
        "segments": [{ "...": "per-leg detail" }]
      }
    ],
    "price_insights": { "lowest_price": 257, "price_level": "low", "typical_price_range": [240, 420] },
    "booking_url": "https://www.google.com/travel/flights?tfs=...",
    "serpapi_searches_used": 1
  }
}
```

## Timeouts

`orchestrator/executor.py` allows this tool 120 seconds. The HTTP call itself is 45 seconds, raised to 90 when `deep_search` is enabled — that flag makes results match the Google Flights website exactly at the cost of latency, so reserve it for when the prices are being questioned.

## Setup

`SERP_API_KEY` is the only credential, and it is shared with the existing SerpApi tools. The keyless fallback needs `fast-flights` from `requirements.txt`. After adding or editing the tool, run `./bin/sync-tools.py cloud` (and `local`) so Tool RAG can retrieve it.

## What this tool does not do

- No booking, seat selection, or payment.
- No live flight status, gate, or delay tracking, and no aircraft positions.
- No hotels or car rentals — use `serpapi_hotel_search` for lodging.
