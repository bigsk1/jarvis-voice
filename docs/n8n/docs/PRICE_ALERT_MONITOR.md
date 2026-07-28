# Price Alert Monitor - n8n Workflow Guide

> Monitor crypto and stock prices, send TTS alerts to Jarvis when thresholds are hit.

**Version**: 5.2
**Last Updated**: July 2026
**Workflow File**: `docs/n8n/workflows/Price Alert Monitor.json`

---

## Overview

The Price Alert Monitor workflow:
1. Fetches price-alert data from the Jarvis API (`data/price-alerts.yaml`)
2. Gets crypto prices from CoinGecko
3. Gets stock/futures prices from Jarvis `/api/prices`
4. Compares against YAML thresholds
5. Sends TTS-friendly alerts to Jarvis

**Single Source of Truth**: Edit `data/price-alerts.yaml` to change thresholds!

---

## Workflow Diagram

```
┌─────────────────┐
│ Every 10 Min    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Fetch Alerts    │──────────────────────────┐
│  (Jarvis API)   │                          │
└────────┬────────┘                          │
         │                                   │
    ┌────┴────┬──────────┐                   │
    ▼         ▼          ▼                   ▼
┌───────┐ ┌───────┐ ┌───────┐        ┌────────────┐
│Crypto │ │ TSLA  │ │ Gold  │        │ Config     │
│Prices │ │ Price │ │ Price │        │ (direct)   │
└───┬───┘ └───┬───┘ └───┬───┘        └─────┬──────┘
    │         │         │                  │
    └────┬────┴────┬────┘                  │
         │         │                       │
         ▼         ▼                       ▼
    ┌─────────────────────────────────────────┐
    │         Wait For All Data               │
    │         (Merge - Append)                │
    └────────────────┬────────────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────────────┐
    │         Check Thresholds                │
    │         (Code Node - JavaScript)        │
    └────────────────┬────────────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────────────┐
    │         Has Alerts?                     │
    │         (Filter)                        │
    └────────────────┬────────────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────────────┐
    │         Send Alert to Jarvis            │
    │         (POST /api/alerts)              │
    └─────────────────────────────────────────┘
```

---

## Configuration

### YAML Config File: `data/price-alerts.yaml`

Jarvis creates this ignored runtime file on first use by copying the tracked
`data/price-alerts.yaml.example` template. Both the live file and its seed
therefore live beside each other under the Docker-mounted `data/` directory.

```yaml
settings:
  check_interval_minutes: 10
  cooldown_hours: 4
  jarvis_api_url: http://localhost:8880

watchlist:
  crypto:
    - symbol: BTC
      name: Bitcoin
      enabled: true
      conditions:
        - type: above
          value: 100000
          severity: high
        - type: below
          value: 85000
          severity: high
        - type: percent_change_24h
          value: 8
          severity: high

    - symbol: SOL
      name: Solana
      enabled: true
      conditions:
        - type: above
          value: 200
          severity: high
        - type: below
          value: 120
          severity: high

  stocks:
    - symbol: TSLA
      name: Tesla
      enabled: true
      conditions:
        - type: above
          value: 450
          severity: high
        - type: below
          value: 350
          severity: high
        - type: percent_change_24h
          value: 5
          severity: high

    - symbol: GC=F
      name: Gold Futures
      enabled: true
      conditions:
        - type: above
          value: 4800
          severity: high
        - type: below
          value: 4400
          severity: high
```

### Condition Types

| Type | Description | Example |
|------|-------------|---------|
| `above` | Alert when price >= value | `{ type: above, value: 100000 }` |
| `below` | Alert when price <= value | `{ type: below, value: 85000 }` |
| `percent_change_24h` | Alert when 24h change >= value % | `{ type: percent_change_24h, value: 8 }` |

---

## Adding New Assets

### Step 1: Update YAML Config

Add the asset to `data/price-alerts.yaml`:

**For Crypto:**
```yaml
watchlist:
  crypto:
    # ... existing coins ...
    - symbol: ETH
      coingecko_id: ethereum  # Required for CoinGecko
      name: Ethereum
      enabled: true
      conditions:
        - type: above
          value: 4000
          severity: high
        - type: below
          value: 3000
          severity: high
```

**For Stocks/Futures:**
```yaml
watchlist:
  stocks:
    # ... existing stocks ...
    - symbol: AAPL
      name: Apple
      enabled: true
      conditions:
        - type: above
          value: 200
          severity: high
```

### Step 2: Add Fetch Node in n8n

**For NEW Crypto (via CoinGecko):**

Update the existing "Fetch Crypto Prices" URL to include new coin IDs:
```
https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana,ethereum&vs_currencies=usd&include_24hr_change=true
```

**For NEW Stocks/Futures:**

1. Add new HTTP Request node:
   - **Name**: `Fetch AAPL Direct`
   - **Method**: GET
   - **URL**: `http://localhost:8880/api/prices/stock/AAPL`
   - **Timeout**: 30000

2. Connect it:
   - **Input**: From "Fetch Config"
   - **Output**: To "Wait For All Data" (new input)

### Step 3: Update Merge Node

1. Click on "Wait For All Data"
2. Increase `numberInputs` by 1
3. Wire the new fetch node to the new input

### Step 4: Update Code Node

Add parsing for the new asset in "Check Thresholds":

**For new crypto (already handled by CoinGecko response):**

The existing code automatically handles any coin in the CoinGecko response:
```javascript
// Already handles cryptoData.ethereum, cryptoData.solana, etc.
```

**For new stocks/futures:**

Add identification logic:
```javascript
// In the for loop that identifies data sources:
else if (json.ok && json.data && json.data.symbol) {
  const symbol = json.data.symbol;
  if (symbol === 'TSLA') {
    tslaData = json.data;
  } else if (symbol === 'GC=F') {
    goldData = json.data;
  } else if (symbol === 'AAPL') {  // ADD THIS
    aaplData = json.data;
  }
}
```

Add threshold checking:
```javascript
// Check AAPL (ADD THIS BLOCK)
if (aaplData) {
  const price = aaplData.price_usd;
  const change = aaplData.change_today_percent || 0;
  const name = 'Apple';
  
  const aboveThresh = getThreshold(config.watchlist, 'stocks', 'AAPL', 'above');
  const belowThresh = getThreshold(config.watchlist, 'stocks', 'AAPL', 'below');
  const changeThresh = getThreshold(config.watchlist, 'stocks', 'AAPL', 'percent_change_24h');
  
  if (price && aboveThresh && price >= aboveThresh.value) {
    alerts.push({
      title: `${name} is at ${priceToSpeech(price)}, above your ${priceToSpeech(aboveThresh.value)} target`,
      description: `${name} above ${priceToSpeech(aboveThresh.value)}!`,
      severity: 'high',
      source: 'price_monitor',
      metadata: { symbol: 'AAPL', price, threshold: aboveThresh.value, type: 'above' }
    });
  }
  // ... below and percent_change checks ...
}
```

---

## Code Node Reference

### Data Identification

The Code node identifies data sources by their response structure:

```javascript
for (const item of allItems) {
  const json = item.json;
  
  // Config: has 'watchlist' key
  if (json.watchlist) {
    config = json;
  }
  // CoinGecko: has 'bitcoin' or 'solana' keys
  else if (json.bitcoin || json.solana) {
    cryptoData = json;
  }
  // Jarvis /api/prices: has 'ok', 'data', and 'data.symbol'
  else if (json.ok && json.data && json.data.symbol) {
    const symbol = json.data.symbol;
    if (symbol === 'TSLA') tslaData = json.data;
    else if (symbol === 'GC=F') goldData = json.data;
  }
}
```

### TTS-Friendly Price Formatting

```javascript
function priceToSpeech(price) {
  // Check if price is a whole number (no meaningful cents)
  const isWhole = price % 1 === 0 || Math.abs(price % 1) < 0.01;
  
  if (price >= 1000000) {
    const millions = price / 1000000;
    return isWhole ? `${Math.round(millions)} million dollars` : `${millions.toFixed(1)} million dollars`;
  } else if (price >= 1000) {
    return `${Math.round(price).toLocaleString()} dollars`;
  } else {
    // For small prices: $400 not $400.00, but $142.50 keeps cents
    return isWhole ? `${Math.round(price)} dollars` : `${price.toFixed(2)} dollars`;
  }
}
```

**Examples:**
- `94994` → "94,994 dollars"
- `4595.40` → "4,595 dollars"
- `400` → "400 dollars" (NOT "400.00 dollars")
- `400.00` → "400 dollars" (drops .00)
- `142.50` → "142.50 dollars" (keeps real cents)
- `1500000` → "2 million dollars"

### Threshold Helper

```javascript
function getThreshold(watchlist, assetType, symbol, conditionType) {
  const assets = watchlist[assetType] || [];
  const asset = assets.find(a => a.symbol === symbol && a.enabled !== false);
  if (!asset) return null;
  const cond = (asset.conditions || []).find(c => c.type === conditionType);
  return cond ? { value: cond.value, name: asset.name } : null;
}

// Usage:
const aboveThresh = getThreshold(config.watchlist, 'stocks', 'TSLA', 'above');
// Returns: { value: 450, name: 'Tesla' } or null
```

---

## Common Stock/Futures Symbols

| Asset | Symbol | Type |
|-------|--------|------|
| Tesla | `TSLA` | Stock |
| Apple | `AAPL` | Stock |
| NVIDIA | `NVDA` | Stock |
| Gold Futures | `GC=F` | Futures |
| Silver Futures | `SI=F` | Futures |
| Oil Futures | `CL=F` | Futures |
| EUR/USD | `EURUSD=X` | Forex |

---

## Troubleshooting

### Alert Not Speaking

1. Check severity is `high` or `critical` (medium won't speak)
2. Verify Jarvis API is running: `curl http://localhost:8880/api/health`

### Config Not Loading

1. Check API endpoint: `curl http://localhost:8880/api/price-alerts`
2. If error, sends "Price monitor config error" alert

### Stock Price Returns Error

1. Verify symbol: `curl http://localhost:8880/api/prices/stock/TSLA`
2. Futures need `=F` suffix: `GC=F` not `GC`
3. Check proxy is working (required for Yahoo Finance)

### Merge Node Issues

- Ensure "Wait For All Data" has correct `numberInputs`
- All inputs must be wired before Code node runs

---

## Related Files

| File | Purpose |
|------|---------|
| `data/price-alerts.yaml` | Live threshold configuration |
| `data/price-alerts.yaml.example` | Tracked safe empty template |
| `docs/n8n/workflows/Price Alert Monitor.json` | Workflow export |
| `api/routes/prices.py` | Direct price API |
| `api/routes/price_alerts.py` | Price-alert data API |
| `skills/stock_price.py` | Stock price tool |
| `skills/crypto_price.py` | Crypto price tool |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 5.2 | Jul 2026 | Data-only runtime/template layout and first-class `/api/price-alerts` endpoint |
| 5.1 | Jun 2026 | Move mutable threshold storage to `data/price-alerts.yaml` |
| 5.0 | Jan 2026 | TTS-friendly titles, no fallback config |
| 4.0 | Jan 2026 | Fetch config from YAML API |
| 3.0 | Jan 2026 | Direct /api/prices endpoints |
| 2.0 | Jan 2026 | Added Wait For All Data merge |
| 1.0 | Jan 2026 | Initial workflow |
