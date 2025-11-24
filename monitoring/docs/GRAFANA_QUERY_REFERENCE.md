# Grafana Query Reference for Jarvis Monitoring

**Purpose**: Complete reference of all LogQL (Loki) and PromQL (Prometheus) queries available for building custom Grafana dashboards.

**Last Updated**: November 24, 2025

---

## Table of Contents

1. [LLM Call Logs (Loki)](#llm-call-logs-loki)
2. [Tool Call Logs (Loki)](#tool-call-logs-loki)
3. [API Metrics (Prometheus)](#api-metrics-prometheus)
4. [Query Patterns & Examples](#query-patterns--examples)
5. [Advanced Filtering](#advanced-filtering)
6. [Dashboard Panel Types](#dashboard-panel-types)

---

## LLM Call Logs (Loki)

### Base Query
```logql
{job="jarvis", log_type="llm"}
```

### Available Fields (Labels)

Extracted by Promtail from `logs/llm-calls-*.jsonl`:

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `model` | label | LLM model name | `claude-sonnet-4-5-20250929`, `grok-beta`, `qwen3:14b` |
| `provider` | label | LLM provider | `anthropic`, `xai`, `openai`, `ollama` |
| `mode` | label | Execution mode | `cloud`, `local` |
| `prompt_type` | label | Type of LLM call | `routing`, `qa`, `condensing`, `thinking` |
| `success` | label | Call succeeded | `true`, `false` |
| `response_type` | label | Response format | `tool`, `text` |
| `timestamp` | field | ISO 8601 timestamp | `2025-11-24T05:13:01.893Z` |
| `duration_ms` | field | Call duration (ms) | `1234.56` |
| `total_tokens` | field | Total tokens used | `9450` |
| `input_tokens` | field | Input tokens | `9050` |
| `output_tokens` | field | Output tokens | `400` |
| `cost_usd` | field | Call cost in USD | `0.033225` |
| `error` | field | Error message (if failed) | `"Rate limit exceeded"` |
| `user_query` | field | Original user question | `"What's the weather?"` |
| `tool_name` | field | Tool selected (if routing) | `get_weather` |

### Example Queries

#### Count all LLM calls
```logql
count_over_time({job="jarvis", log_type="llm"}[24h])
```

#### Count by provider
```logql
sum by(provider) (count_over_time({job="jarvis", log_type="llm"}[24h]))
```

#### Count by model
```logql
sum by(model) (count_over_time({job="jarvis", log_type="llm"}[24h]))
```

#### Total tokens used (last 24h)
```logql
sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap total_tokens [24h]))
```

#### Total cost (last 24h)
```logql
sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h]))
```

#### Average response time by model
```logql
avg by(model) (avg_over_time({job="jarvis", log_type="llm"} | json | unwrap duration_ms [1h]))
```

#### Failed LLM calls only
```logql
{job="jarvis", log_type="llm", success="false"} | json
```

#### Routing calls only
```logql
{job="jarvis", log_type="llm", prompt_type="routing"} | json
```

#### Cost per provider (pie chart)
```logql
sum by(provider) (sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h]))
```

#### Most expensive queries (top 10)
```logql
topk(10, 
  sum by(user_query) (
    sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h])
  )
)
```

#### Token usage by prompt type
```logql
sum by(prompt_type) (sum_over_time({job="jarvis", log_type="llm"} | json | unwrap total_tokens [24h]))
```

---

## Tool Call Logs (Loki)

### Base Query
```logql
{job="jarvis", log_type="tools"}
```

### Available Fields (Labels)

Extracted by Promtail from `logs/tools/tool-calls-*.jsonl`:

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `tool` | label | Tool name | `mcp_brave_search_brave_web_search`, `crypto_price`, `opencode` |
| `mode` | label | Execution mode | `cloud`, `local` |
| `result_ok` | label | Tool succeeded | `true`, `false` |
| `has_data` | label | Result has data | `true`, `false` |
| `timestamp` | field | ISO 8601 timestamp | `2025-11-24T01:16:31.017Z` |
| `duration_ms` | field | Execution time (ms) | `570.76` |
| `user_query` | field | Original question (if available) | `"What's Bitcoin price?"` |
| `arguments` | field | Tool parameters (JSON) | `{"query": "bitcoin", "count": 10}` |
| `result` | field | Full result object (JSON) | `{"ok": true, "speech": "...", "data": {...}}` |
| `error` | field | Error message (if failed) | `"Connection timeout"` |

### Example Queries

#### Count all tool calls
```logql
count_over_time({job="jarvis", log_type="tools"}[24h])
```

#### Count by tool name
```logql
sum by(tool) (count_over_time({job="jarvis", log_type="tools"}[24h]))
```

#### Top 10 most used tools
```logql
topk(10, 
  sum by(tool) (count_over_time({job="jarvis", log_type="tools"}[24h]))
)
```

#### Failed tool calls only
```logql
{job="jarvis", log_type="tools", result_ok="false"} | json
```

#### Average execution time by tool
```logql
avg by(tool) (avg_over_time({job="jarvis", log_type="tools"} | json | unwrap duration_ms [1h]))
```

#### Slowest tools (top 5)
```logql
topk(5, 
  avg by(tool) (avg_over_time({job="jarvis", log_type="tools"} | json | unwrap duration_ms [1h]))
)
```

#### Tool success rate (percentage)
```logql
sum(count_over_time({job="jarvis", log_type="tools", result_ok="true"}[24h])) 
/ 
sum(count_over_time({job="jarvis", log_type="tools"}[24h])) 
* 100
```

#### MCP tools only
```logql
{job="jarvis", log_type="tools", tool=~"mcp_.*"} | json
```

#### Search tools only
```logql
{job="jarvis", log_type="tools", tool=~".*search.*"} | json
```

#### Tool calls over time (rate per minute)
```logql
rate({job="jarvis", log_type="tools"}[5m])
```

---

## API Metrics (Prometheus)

### Base Metrics

Scraped from `http://192.168.70.228:8880/metrics` (Jarvis API)

| Metric | Type | Description | Labels |
|--------|------|-------------|--------|
| `http_requests_total` | counter | Total HTTP requests | `method`, `handler`, `status` |
| `http_request_duration_seconds` | histogram | Request duration | `method`, `handler` |
| `http_requests_in_progress` | gauge | Active requests | `method`, `handler` |
| `process_cpu_seconds_total` | counter | CPU time used | - |
| `process_resident_memory_bytes` | gauge | Memory usage | - |
| `process_open_fds` | gauge | Open file descriptors | - |

### Example Queries

#### Total API requests (24h)
```promql
sum(increase(http_requests_total[24h]))
```

#### Requests per minute (rate)
```promql
sum(rate(http_requests_total[5m])) * 60
```

#### Requests by endpoint
```promql
sum by(handler) (increase(http_requests_total[24h]))
```

#### Success rate (2xx responses)
```promql
sum(rate(http_requests_total{status=~"2.."}[5m])) 
/ 
sum(rate(http_requests_total[5m])) 
* 100
```

#### Error rate (5xx responses)
```promql
sum(rate(http_requests_total{status=~"5.."}[5m])) 
/ 
sum(rate(http_requests_total[5m])) 
* 100
```

#### Average response time (seconds)
```promql
rate(http_request_duration_seconds_sum[5m]) 
/ 
rate(http_request_duration_seconds_count[5m])
```

#### 95th percentile response time
```promql
histogram_quantile(0.95, 
  rate(http_request_duration_seconds_bucket[5m])
)
```

#### API uptime (percentage, last 24h)
```promql
(1 - (sum(increase(http_requests_total{status=~"5.."}[24h])) / sum(increase(http_requests_total[24h])))) * 100
```

#### Memory usage (MB)
```promql
process_resident_memory_bytes / 1024 / 1024
```

#### CPU usage (percentage)
```promql
rate(process_cpu_seconds_total[5m]) * 100
```

---

## Query Patterns & Examples

### Time Ranges

| Pattern | Description | Example |
|---------|-------------|---------|
| `[5m]` | Last 5 minutes | `count_over_time({...}[5m])` |
| `[1h]` | Last 1 hour | `count_over_time({...}[1h])` |
| `[24h]` | Last 24 hours | `count_over_time({...}[24h])` |
| `[7d]` | Last 7 days | `count_over_time({...}[7d])` |

### Aggregation Functions

#### Loki (LogQL)
```logql
sum(...)           # Total sum
avg(...)           # Average
max(...)           # Maximum value
min(...)           # Minimum value
count(...)         # Count entries
topk(N, ...)       # Top N results
bottomk(N, ...)    # Bottom N results
```

#### Prometheus (PromQL)
```promql
sum(...)           # Total sum
avg(...)           # Average
max(...)           # Maximum
min(...)           # Minimum
count(...)         # Count
rate(...)          # Per-second rate
increase(...)      # Total increase over time
histogram_quantile(0.95, ...) # 95th percentile
```

### Rate Functions

```logql
# LogQL - Calculate rate
rate({job="jarvis", log_type="tools"}[5m])

# PromQL - Requests per second
rate(http_requests_total[5m])

# PromQL - Requests per minute
rate(http_requests_total[5m]) * 60
```

### Filtering by Multiple Labels

```logql
# AND condition (comma-separated)
{job="jarvis", log_type="llm", provider="anthropic"}

# OR condition (regex)
{job="jarvis", log_type="llm", provider=~"anthropic|xai"}

# NOT condition (negative regex)
{job="jarvis", log_type="llm", provider!="ollama"}
```

---

## Advanced Filtering

### Regex Patterns

```logql
# Tools starting with "mcp_"
{job="jarvis", log_type="tools", tool=~"mcp_.*"}

# Search-related tools
{job="jarvis", log_type="tools", tool=~".*search.*"}

# Multiple providers
{job="jarvis", log_type="llm", provider=~"anthropic|xai|openai"}

# Exclude local mode
{job="jarvis", mode!="local"}

# HTTP success codes (2xx)
{status=~"2.."}

# HTTP error codes (4xx or 5xx)
{status=~"[45].."}
```

### JSON Field Extraction

```logql
# Extract and filter by JSON field
{job="jarvis", log_type="llm"} 
| json 
| user_query =~ ".*weather.*"

# Extract numeric field for math
{job="jarvis", log_type="llm"} 
| json 
| unwrap cost_usd

# Multiple conditions
{job="jarvis", log_type="llm"} 
| json 
| provider = "anthropic"
| model =~ ".*sonnet.*"
```

### Line Filtering

```logql
# Contains text
{job="jarvis", log_type="llm"} |= "error"

# Does not contain text
{job="jarvis", log_type="llm"} != "success"

# Regex match
{job="jarvis", log_type="llm"} |~ "error|failed|timeout"

# Regex not match
{job="jarvis", log_type="llm"} !~ "success"
```

---

## Dashboard Panel Types

### 1. Stat Panel (Single Value)

**Best for**: Total counts, averages, current values

```logql
# Total LLM calls (24h)
sum(count_over_time({job="jarvis", log_type="llm"}[24h]))

# Total cost (24h)
sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h]))

# Average response time (1h)
avg(avg_over_time({job="jarvis", log_type="llm"} | json | unwrap duration_ms [1h]))
```

**Panel Settings**:
- `queryType`: `instant` (for single value)
- `graphMode`: `none` or `area` (for sparkline)
- `colorMode`: `value` or `background`

---

### 2. Time Series (Graph)

**Best for**: Trends over time, comparing multiple series

```logql
# LLM calls over time (rate per minute)
sum(rate({job="jarvis", log_type="llm"}[5m])) * 60

# Cost over time by provider
sum by(provider) (rate({job="jarvis", log_type="llm"} | json | unwrap cost_usd [5m]))

# Tool calls over time by tool
sum by(tool) (rate({job="jarvis", log_type="tools"}[5m]))
```

**Panel Settings**:
- `queryType`: `range`
- `legendDisplayMode`: `list` or `table`
- `tooltipMode`: `multi` (show all series)

---

### 3. Pie Chart

**Best for**: Distribution, percentages, proportions

```logql
# Calls by provider
sum by(provider) (count_over_time({job="jarvis", log_type="llm"}[24h]))

# Cost by model
sum by(model) (sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h]))

# Tool usage distribution
sum by(tool) (count_over_time({job="jarvis", log_type="tools"}[24h]))
```

**Panel Settings**:
- `legendDisplayMode`: `table`
- `legendPlacement`: `right`
- `legendValues`: `["value", "percent"]`

---

### 4. Bar Gauge

**Best for**: Comparing multiple items, rankings

```logql
# Top 10 most expensive models
topk(10, 
  sum by(model) (sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h]))
)

# Slowest tools
topk(10, 
  avg by(tool) (avg_over_time({job="jarvis", log_type="tools"} | json | unwrap duration_ms [1h]))
)
```

**Panel Settings**:
- `orientation`: `horizontal`
- `displayMode`: `gradient`
- `thresholds`: Set green/yellow/red zones

---

### 5. Table

**Best for**: Detailed data, multiple columns, sorting

```logql
# Tool statistics (count, avg time, failures)
sum by(tool) (count_over_time({job="jarvis", log_type="tools"}[24h]))
```

**Panel Settings**:
- Add multiple queries for different columns
- `displayMode`: `color-background` for cells
- `filterable`: true (enable column filters)

---

### 6. Logs Panel

**Best for**: Raw log viewing, debugging

```logql
# Recent LLM calls
{job="jarvis", log_type="llm"} | json

# Failed tool calls
{job="jarvis", log_type="tools", result_ok="false"} | json

# Search logs by keyword
{job="jarvis", log_type="llm"} |= "weather" | json
```

**Panel Settings**:
- `dedupStrategy`: `none` or `exact`
- `enableLogDetails`: true
- `showTime`: true
- `sortOrder`: `Descending` (newest first)

---

### 7. Heatmap

**Best for**: Response time distribution, patterns over time

```promql
# Response time distribution
sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
```

**Panel Settings**:
- `format`: `heatmap`
- `yAxis`: Buckets (response times)
- `xAxis`: Time

---

## Quick Start Templates

### Template 1: Cost Dashboard

```json
{
  "panels": [
    {
      "title": "Total Cost (24h)",
      "type": "stat",
      "targets": [{
        "expr": "sum(sum_over_time({job=\"jarvis\", log_type=\"llm\"} | json | unwrap cost_usd [24h]))"
      }]
    },
    {
      "title": "Cost by Provider",
      "type": "piechart",
      "targets": [{
        "expr": "sum by(provider) (sum_over_time({job=\"jarvis\", log_type=\"llm\"} | json | unwrap cost_usd [24h]))"
      }]
    },
    {
      "title": "Cost Over Time",
      "type": "timeseries",
      "targets": [{
        "expr": "sum(rate({job=\"jarvis\", log_type=\"llm\"} | json | unwrap cost_usd [5m]))"
      }]
    }
  ]
}
```

---

### Template 2: Performance Dashboard

```json
{
  "panels": [
    {
      "title": "Average Response Time",
      "type": "stat",
      "targets": [{
        "expr": "avg(avg_over_time({job=\"jarvis\", log_type=\"llm\"} | json | unwrap duration_ms [1h]))"
      }]
    },
    {
      "title": "Slowest Tools",
      "type": "bargauge",
      "targets": [{
        "expr": "topk(10, avg by(tool) (avg_over_time({job=\"jarvis\", log_type=\"tools\"} | json | unwrap duration_ms [1h])))"
      }]
    },
    {
      "title": "Response Time Trend",
      "type": "timeseries",
      "targets": [{
        "expr": "avg(rate({job=\"jarvis\", log_type=\"llm\"} | json | unwrap duration_ms [5m]))"
      }]
    }
  ]
}
```

---

### Template 3: Error Tracking Dashboard

```json
{
  "panels": [
    {
      "title": "Failed LLM Calls",
      "type": "stat",
      "targets": [{
        "expr": "sum(count_over_time({job=\"jarvis\", log_type=\"llm\", success=\"false\"}[24h]))"
      }]
    },
    {
      "title": "Failed Tool Calls",
      "type": "stat",
      "targets": [{
        "expr": "sum(count_over_time({job=\"jarvis\", log_type=\"tools\", result_ok=\"false\"}[24h]))"
      }]
    },
    {
      "title": "Recent Errors",
      "type": "logs",
      "targets": [{
        "expr": "{job=\"jarvis\"} | json | success = \"false\" or result_ok = \"false\""
      }]
    }
  ]
}
```

---

## Tips & Best Practices

### 1. **Use Instant Queries for Stat Panels**
```logql
# Good (instant)
sum(count_over_time({...}[24h]))

# Bad (range - causes multiple values)
count_over_time({...}[24h])
```

### 2. **Optimize Query Performance**
- Use smaller time ranges for instant queries (`[1h]` instead of `[24h]`)
- Remove `| json` from count queries (only needed when filtering by JSON fields)
- Set appropriate dashboard refresh rates (1m, not 5s)

### 3. **Label Extraction in Promtail (Not in Queries)**
Labels like `model`, `provider`, `tool` are already extracted by Promtail config.
Don't re-extract in queries - just use them directly:

```logql
# Good (uses pre-extracted label)
{job="jarvis", log_type="llm", provider="anthropic"}

# Bad (slower, re-parses JSON)
{job="jarvis", log_type="llm"} | json | provider = "anthropic"
```

### 4. **Use sum() to Aggregate Multi-Series**
```logql
# Good (single value for stat panel)
sum(count_over_time({...}[24h]))

# Bad (multiple time series, breaks stat panel)
count_over_time({...}[24h])
```

### 5. **Format Currency Values**
In panel settings:
- Unit: `currencyUSD` or `short`
- Decimals: `2` for currency

### 6. **Set Appropriate Time Ranges**
- Recent activity: `Last 1 hour`
- Daily trends: `Last 24 hours`
- Weekly analysis: `Last 7 days`

---

## Troubleshooting

### "No data" in panel
1. Check time range (expand to "Last 24 hours")
2. Verify logs exist: `tail -10 logs/llm-calls-*.jsonl`
3. Check Promtail is running: `docker ps | grep promtail`
4. Test query in Grafana "Explore" tab

### "Too many outstanding requests" (500 error)
1. Reduce time range: `[24h]` → `[1h]`
2. Remove `| json` from count queries
3. Set refresh to 1 minute (not 5 seconds)

### Panel shows multiple values instead of one
- Add `sum()` wrapper: `sum(count_over_time({...}[24h]))`
- Use `queryType: instant` for stat panels

---

## Related Files

- Promtail Config: `monitoring/promtail-config.yml` (defines label extraction)
- Existing Dashboards: `monitoring/grafana/dashboards/*.json`
- LLM Logger: `lib/llm_logger.py` (generates LLM logs)
- Tool Logger: `lib/tool_logger.py` (generates tool logs)

---

**Need help?**
- LogQL Docs: https://grafana.com/docs/loki/latest/logql/
- PromQL Docs: https://prometheus.io/docs/prometheus/latest/querying/basics/
- Grafana Panels: https://grafana.com/docs/grafana/latest/panels-visualizations/

**Created**: November 24, 2025  
**Jarvis Version**: v2 (Multi-turn orchestrator with LLM logging)

