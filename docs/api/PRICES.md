# Prices API

> Direct price retrieval without LLM routing - fast, free, silent.

**Version**: 1.0  
**Last Updated**: January 2026

---

## Overview

The Prices API provides direct access to stock and crypto prices without going through LLM routing. This is ideal for:
- **n8n workflows** - Fast price checks without token usage
- **Monitoring systems** - Silent background checks
- **Dashboards** - Real-time price displays
- **Batch operations** - Multiple prices in one call

**Key Benefits:**
| Feature | Query API | Prices API |
|---------|-----------|------------|
| Speed | ~15-20s (LLM routing) | ~2-3s (direct) |
| Cost | Uses tokens | Free |
| Output | Speech + response | Data only |
| Best for | Natural language | Automated checks |

---

## Endpoints

### Stock/Futures Price

```bash
GET /api/prices/stock/{symbol}
```

**Supported Symbols:**
- Stocks: `TSLA`, `AAPL`, `GOOGL`, `MSFT`, `NVDA`, `META`, `AMZN`
- Futures: `GC=F` (Gold), `SI=F` (Silver), `CL=F` (Oil)
- Forex: `EURUSD=X`, `GBPUSD=X`, `USDJPY=X`

**Example:**
```bash
# Get Tesla price
curl http://localhost:8880/api/prices/stock/TSLA | jq

# Get Gold futures
curl http://localhost:8880/api/prices/stock/GC=F | jq
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "symbol": "TSLA",
    "company": "Tesla, Inc.",
    "price_usd": 437.50,
    "change_today_usd": -2.00,
    "change_today_percent": -0.46,
    "change_emoji": "📉",
    "volume": 57439833,
    "market_cap_usd": 1455045869568,
    "market_cap_display": "$1.46T",
    "pe_ratio": 303.82,
    "52_week_high": 498.83,
    "52_week_low": 214.25,
    "sector": "Consumer Cyclical",
    "source": "Yahoo Finance",
    "proxy_enabled": true
  }
}
```

### Crypto Price

```bash
GET /api/prices/crypto/{symbol}
```

**Supported Symbols:** `BTC`, `ETH`, `SOL`, `ADA`, `DOT`, `LINK`, etc.

**Example:**
```bash
# Get Bitcoin price
curl http://localhost:8880/api/prices/crypto/BTC | jq

# Get Solana price
curl http://localhost:8880/api/prices/crypto/SOL | jq
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "symbol": "BTC",
    "name": "Bitcoin",
    "price_usd": 94994.00,
    "change_24h_percent": 1.42,
    "change_emoji": "📈",
    "market_cap_usd": 1876543210000,
    "volume_24h_usd": 45678901234,
    "source": "CoinGecko"
  }
}
```

### Crypto Chart

```bash
GET /api/prices/crypto/{symbol}/chart
```

Get structured CoinGecko chart data for web UI charts, monitoring dashboards, or canvas visualizations.

**Query Parameters:**
- `days` - Chart range such as `1`, `7`, `30`, `90`, `365`, or `max`
- `vs_currency` - Quote currency, default `usd`
- `points_limit` - Optional max number of points to return

**Example:**
```bash
# Get a 30-day Bitcoin chart
curl "http://localhost:8880/api/prices/crypto/BTC/chart?days=30&points_limit=120" | jq

# Get a 7-day Solana chart in USD
curl "http://localhost:8880/api/prices/crypto/SOL/chart?days=7" | jq
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "coin": "Bitcoin",
    "coin_id": "bitcoin",
    "vs_currency": "usd",
    "days": "30",
    "range_label": "30-day",
    "current_price": 76590.82,
    "change_percent": -0.25,
    "points_returned": 120,
    "original_points": 721,
    "source": "CoinGecko",
    "authenticated": true,
    "proxy_enabled": true,
    "series": {
      "prices": [
        { "timestamp_ms": 1776769225300, "iso": "2026-04-21T11:00:25.300000+00:00", "value": 76784.39 }
      ],
      "market_caps": [
        { "timestamp_ms": 1776769225300, "iso": "2026-04-21T11:00:25.300000+00:00", "value": 1537762754214.86 }
      ],
      "total_volumes": [
        { "timestamp_ms": 1776769225300, "iso": "2026-04-21T11:00:25.300000+00:00", "value": 42109681288.49 }
      ]
    }
  }
}
```

### Batch Prices

```bash
GET /api/prices/batch?stocks=TSLA,GC=F&crypto=BTC,SOL
```

Get multiple prices in a single request.

**Example:**
```bash
curl "http://localhost:8880/api/prices/batch?stocks=TSLA,GC=F&crypto=BTC,SOL" | jq
```

**Response:**
```json
{
  "stocks": [
    { "symbol": "TSLA", "price_usd": 437.50, ... },
    { "symbol": "GC=F", "price_usd": 4595.40, ... }
  ],
  "crypto": [
    { "symbol": "BTC", "price_usd": 94994.00, ... },
    { "symbol": "SOL", "price_usd": 142.10, ... }
  ]
}
```

---

## Config API

The Config API serves the price alert configuration to n8n workflows.

### Get Price Alert Config

```bash
GET /api/config/price-alerts
```

Returns the live `data/price-alerts.yaml` configuration as JSON. Jarvis creates
an empty configuration on first use or migrates the legacy
`config/price-alerts.yaml` file when present.

**Response:**
```json
{
  "ok": true,
  "settings": {
    "check_interval_minutes": 10,
    "cooldown_hours": 4
  },
  "watchlist": {
    "crypto": [
      {
        "symbol": "BTC",
        "name": "Bitcoin",
        "enabled": true,
        "conditions": [
          { "type": "above", "value": 100000, "severity": "high" },
          { "type": "below", "value": 85000, "severity": "high" }
        ]
      }
    ],
    "stocks": [
      {
        "symbol": "TSLA",
        "name": "Tesla",
        "enabled": true,
        "conditions": [
          { "type": "above", "value": 450, "severity": "high" }
        ]
      }
    ]
  },
  "source": "data/price-alerts.yaml"
}
```

### Get Thresholds Only

```bash
GET /api/config/price-alerts/thresholds
```

Returns thresholds in a simplified format for n8n Code nodes.

---

## n8n Integration

The Prices API is designed for n8n workflows. See [PRICE_ALERT_MONITOR.md](../n8n/docs/PRICE_ALERT_MONITOR.md) for:
- How to add new assets to monitoring
- Workflow diagram and node configuration
- Threshold configuration in YAML

**Quick n8n Setup:**
```
HTTP Request Node:
  Method: GET
  URL: http://localhost:8880/api/prices/stock/TSLA
  
Output: Use {{ $json.data.price_usd }} in expressions
```

---

## Error Handling

**Invalid Symbol:**
```json
{
  "ok": false,
  "error": "No data found for 'INVALID'. Check if the ticker symbol is correct.",
  "speech": "No data found for 'INVALID'."
}
```

**API Down:**
HTTP 500 with error details.

---

## Symbol Mapping

The stock price tool includes automatic symbol mapping:

| Query | Maps To |
|-------|---------|
| `tesla` | `TSLA` |
| `apple` | `AAPL` |
| `google` | `GOOGL` |
| `gold` | `GC=F` |
| `silver` | `SI=F` |
| `oil` | `CL=F` |
| `bitcoin` | `BTC` |

---

## Related Documentation

- [API Overview](./API_OVERVIEW.md) - All API endpoints
- [Price Alert Monitor](../n8n/docs/PRICE_ALERT_MONITOR.md) - n8n workflow guide
- [Query API](./QUERY.md) - Natural language queries (uses LLM)
