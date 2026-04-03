# SerpApi Search Tool

Use the SerpApi tools to run web, marketplace, maps, and travel lookups through SerpApi from Jarvis.

The base tool is generic by design, and Jarvis now also includes thin SerpApi wrappers for common domains:

- `serpapi_search` for generic engine-based search
- `serpapi_maps_search` for Google Maps place and local business lookups
- `serpapi_hotel_search` for Google Hotels searches

## Files

- Shared client: `lib/serpapi_client.py`
- Generic tool: `skills/serpapi_search.py`
- Maps wrapper: `skills/serpapi_maps_search.py`
- Hotels wrapper: `skills/serpapi_hotel_search.py`
- Tool definitions:
  - `skills/serpapi_search.tool.json`
  - `skills/serpapi_maps_search.tool.json`
  - `skills/serpapi_hotel_search.tool.json`

## Setup

1. Add your key in env:
   - `SERP_API_KEY` in `config/cloud.env` and/or `config/local.env`
2. Sync tools:
   - `./bin/sync_tools.py cloud`
   - `./bin/sync_tools.py local` (if you use local mode)

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
        "reviews": 1234
      }
    ]
  }
}
```

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

### Maps place search

```json
{
  "query": "coffee shops in Austin",
  "hl": "en",
  "num_results": 5
}
```

### Hotel search

```json
{
  "destination": "San Diego",
  "check_in_date": "2026-05-10",
  "check_out_date": "2026-05-12",
  "adults": 2,
  "max_price": 300,
  "rating": 8,
  "num_results": 5
}
```

## How to prompt Jarvis

Natural prompt:

`Hey Jarvis, find 5 Amazon gift ideas for a 25-year-old tech enthusiast, budget $50-$150, avoid Apple accessories, include links and why each is good.`

Tool-forced follow-up:

`Use serpapi_search with the same query and return 5 options with links.`

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
- proxy/network path is healthy
- `logs/tools/tool-calls-YYYY-MM-DD.jsonl` for exact failing tool

### Results not matching budget

Amazon search quality depends on query wording. Add stronger constraints:

- include budget in query (`$50-$150`)
- exclude brand terms (`-Apple`)
- use `extra_params` for engine-specific filters when needed

## Notes

- Links in `data.results[].url` can be rendered in WebUI and shown in CLI output.
- For cleaner gift recommendations, pair this tool with one synthesis step that filters out low-quality matches.
