---
tool_hints:
  - status_recap
---

# Status Recap

You are providing a comprehensive status briefing using the `status_recap` tool.

## What Status Recap Does

The `status_recap` tool aggregates data from multiple sources into one report:
- 🕐 **Time** - Current date and time
- 🌤️ **Weather** - Current conditions and temperature
- 💰 **Crypto** - Cryptocurrency prices and 24h changes (Bitcoin, Solana by default)
- 📊 **Stocks** - Stock/futures prices and daily changes (Tesla, Gold, Silver by default)
- 🚨 **Alerts** - Any active system alerts
- 📋 **Reminders** - Current reminders: upcoming scheduled plus triggered reminders needing attention
- 💻 **System** - CPU, RAM, disk usage, and uptime
- 🖼️ **Dashboard Image** - Optional AI-generated status visualization

## Output

The tool automatically:
- Saves a full JSON report to **Stash** for later reference
- Creates a **Canvas page** with formatted markdown summary
- Optionally generates a dashboard image (if enabled)

## Usage Options

### Basic Recap (Default)
```
"Give me a status recap"
"What's my current status?"
"Status briefing please"
```
Runs with defaults: weather, crypto (Bitcoin, Solana), stocks (Tesla, Gold, Silver futures), alerts, reminders, system health.

### With Additional Crypto Coins
```
"Status recap with SOL and DOGE prices"
```
Add `crypto_coins` parameter: `["bitcoin", "solana", "dogecoin"]`

### With Custom Stocks/Futures
```
"Status recap with Apple and oil prices"
"Status with NVDA and crude oil"
```
Add `stock_symbols` parameter: `["TSLA", "AAPL", "GC=F", "CL=F"]`

**Supported symbols:**
- Stocks: `TSLA`, `AAPL`, `NVDA`, `MSFT`, `AMZN`, `GOOGL`
- Commodities: `GC=F` (gold), `SI=F` (silver), `CL=F` (oil), `NG=F` (natural gas)
- ETFs: `SPY` (S&P 500), `QQQ` (Nasdaq), `GLD` (gold ETF)

### With Dashboard Image
```
"Status recap with a visual dashboard"
```
Enables the `generate_image` option to create an AI visualization.
Note: Image generation adds ~60 seconds to response time.

### With News Headlines
```
"Status recap plus latest news"
"Give me a recap with today's news"
```
When news is requested, I'll use native grounding search capabilities to fetch top headlines and include them in the summary.

### Specific Sections Only
```
"Just weather and crypto status"
"Only stocks and system health"
```
Use `sections` parameter: `["weather", "crypto", "stocks"]`

Available sections: `time`, `weather`, `crypto`, `stocks`, `alerts`, `reminders`, `system`

## After the Tool Runs

I will:
1. **Summarize** the key points in speech
2. **Highlight** any issues requiring attention (high CPU, active alerts, triggered reminders, overdue reminders)
3. **Reference** the canvas page for full details
4. **Add news** if requested (using native grounding search)

## Canvas Page

The canvas page contains:
- Dashboard image (if generated) at the top
- Full status breakdown by section
- Timestamps and data sources
- Quick reference for follow-up questions

Access recent canvas pages with: `"Show me my latest canvas"` or `"What's on my canvas?"`

## Example Requests

| Request | What Happens |
|---------|--------------|
| "Status recap" | Default briefing (crypto, stocks, weather, system) |
| "Quick status check" | Same as above |
| "Status with image" | Includes AI-generated dashboard |
| "Status plus news" | Briefing + top news headlines |
| "Full status recap with everything" | All sections + image + news |
| "Status with oil and natural gas" | Custom commodities (CL=F, NG=F) |
| "Recap with NVDA and Apple stocks" | Custom stocks added |

## Follow-Up Questions

After a recap, you can ask:
- "Tell me more about the system health"
- "What's the weather forecast for tomorrow?"
- "Why is CPU usage high?"
- "What's the gold price trend?"
- "How's Tesla doing this week?"
- "Show me the full stash report"

I'll use the context from the recap to answer or run additional tools as needed.
