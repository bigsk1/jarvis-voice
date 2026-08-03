# Flight Status Tool

`flight_status` answers "where is that aircraft right now" from live ADS-B transponder broadcasts. It needs no API key, no account, and no new Python dependency — it is plain HTTP through the existing `lib/http_client.py`.

Ask for it the way you would say it out loud:

> "Where is United 2056 right now?"
> "What's flying over Portland?"
> "Track tail number N86534."

## Files

- Tool: `skills/flight_status.py`
- Definition: `skills/flight_status.tool.json`
- Shared place lookup: `lib/geocode.py`
- Tests: `tests/test_flight_status.py`

## What it is not

This is the single most important thing to know about the tool, and the manifest description says it plainly so the model does not overpromise:

**`flight_status` reports transponder positions, not airline operations.** There is no gate, no delay, no cancellation, no scheduled departure or arrival time, and no baggage claim. Those live in keyed commercial feeds. Every successful response carries the same caveat in `data.limitations` so it survives into the model's context.

It follows that an aircraft is only findable while it is broadcasting. A flight that has not pushed back, has already landed, or is over an ocean with no receiver coverage returns a successful response with zero results and an explanation, not an error. That distinction matters: "not found" here means "not currently transmitting," never "no such flight."

## Providers

Both networks are volunteer receiver co-ops sharing the same response shape, so the tool tries them in order and uses whichever answers first.

| Order | Provider | Notes |
|---|---|---|
| 1 | `airplanes.live` | Also returns aircraft description, operator, and build year. |
| 2 | `adsb.lol` | Positions only. Used when the first is unreachable. |

`data.provider` records which one served the response. Both are hobbyist services with no SLA and ask that use stay non-commercial, which a self-hosted assistant satisfies.

## Lookup modes

Exactly one identifier is needed. The tool picks the mode from whichever argument is present.

| Argument | Example | Resolves |
|---|---|---|
| `flight` | `UA2056`, `UA 2056`, `United 2056`, `UAL2056` | One aircraft by callsign |
| `registration` | `N86534` | One aircraft by tail number |
| `hex` | `abe448` | One aircraft by ICAO 24-bit address |
| `location` | `Portland, OR` | Everything flying nearby |
| `latitude` + `longitude` | `45.52`, `-122.68` | Everything flying nearby |

### Flight numbers versus callsigns

People say the IATA flight number ("UA 2056") but transponders broadcast the ICAO callsign ("UAL2056"). `flight_status` translates using an airline table covering the major carriers, and because the providers accept a comma-separated callsign list, every spelling it wants to try costs a single request. Airlines outside the table still work if the raw callsign is given.

### Overhead searches

`location` is resolved through the keyless Open-Meteo geocoder in `lib/geocode.py`, the same one the weather tool uses. Pass `latitude`/`longitude` directly to skip that step.

`radius_nm` defaults to 25 and accepts 1–250. Results are sorted nearest first.

Ground traffic is excluded by default, because near an airport parked and taxiing aircraft otherwise drown out everything actually flying — a 3 nm search over LAX returns 34 aircraft of which only 3 are airborne. Pass `include_ground: true` to keep them. `data.airborne_count` always reports how many were flying, regardless of the filter.

## Response

`data.results[]` entries are flattened into plain units and plain language:

- `callsign`, `airline`, `registration`, `hex`
- `aircraft` (`BOEING 737-800`), `aircraft_type` (`B738`), `year`
- `altitude_ft`, `vertical_trend` (`climbing` / `descending` / `level` / `on the ground`), `vertical_rate_fpm`
- `ground_speed_kt`, `track_deg`, `heading` (`northwest`)
- `latitude`, `longitude`, `distance_nm`, `bearing`
- `on_ground`, `squawk`, `emergency`, `position_age_seconds`
- `map_url` — a live map centered on the aircraft

`emergency` is `null` in the ordinary case rather than the literal string `"none"` the feed sends, so a set value always means something is actually wrong.

Altitude needs care: the feed reports a parked aircraft's altitude as the string `"ground"`, not a number. The tool converts that to `on_ground: true` with a null `altitude_ft` so nothing downstream has to special-case a string in a numeric field.

## Example

```bash
python3 skills/flight_status.py '{"flight": "UA2056"}'
python3 skills/flight_status.py '{"location": "Portland, OR", "radius_nm": 60}'
python3 skills/flight_status.py '{"registration": "N86534"}'
```

Speech from the first:

> United 2056 is at 21,400 feet and climbing, doing 396 knots heading northwest. It's a BOEING 737-800.

## Follow-up turns

`followup_extractor.py` has a dedicated `flight_status` branch that keeps the callsign, registration, hex, operator, aircraft, altitude, speed, heading, and distance for each result. The hex and registration are the useful handles: a later "where is it now?" can re-query the exact aircraft without re-deriving anything, and the transponder telemetry a follow-up has no use for is dropped.

## Timeouts

Each provider call uses a 15 second HTTP timeout and the tool runs under the executor's default subprocess limit. An overhead search makes at most two calls (geocode, then positions), so no dedicated timeout entry is needed.

## Setup

None. Both ADS-B networks and the geocoder are keyless, so the tool works in every profile with no new environment variable.

## Related

- `flight_search` — prices, schedules, and booking links. Use it for anything involving buying a ticket; use `flight_status` for where an aircraft physically is.
