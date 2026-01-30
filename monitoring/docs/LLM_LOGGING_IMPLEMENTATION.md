# LLM Logging Implementation Summary

## 🎉 What Was Implemented

Complete LLM call logging and monitoring system for Jarvis, with specialized Grafana dashboards.

---

## ✅ Components Built

### 1. **LLM Logger** (`lib/llm_logger.py`)
- Tracks all LLM API calls in JSONL format
- Captures:
  - Provider (xAI, Anthropic, OpenAI, Ollama)
  - Model name
  - Prompt type (routing, chat, tool_selection)
  - Token usage and cost
  - Response times
  - Success/failure status
  - Thinking/reasoning output (for reasoning models)
- Daily log rotation: `logs/llm-calls-YYYY-MM-DD.jsonl`

### 2. **Router Integration** (`orchestrator/router_v2.py`)
- Automatically logs every LLM call during routing
- Tracks timing from request to response
- Captures full usage metadata for cost analysis
- Handles errors gracefully

### 3. **Updated Promtail Configuration**
- Correctly parses tool logs (from `lib/tool_logger.py`)
- Correctly parses LLM logs (from `lib/llm_logger.py`)
- Extracts labels for efficient filtering:
  - **Tool logs**: `tool_name`, `mode`, `result_ok`
  - **LLM logs**: `model`, `provider`, `mode`, `prompt_type`, `success`, `response_type`

### 4. **New Grafana Dashboards**

#### **Jarvis LLM Performance** (`jarvis-llm-performance.json`)
- Total LLM calls (24h)
- Total cost in USD (24h)
- Average response time
- Total tokens used
- Response time by model (time series)
- Calls by model (table)
- Cost by provider (table)
- Recent LLM calls (raw logs)

#### **Jarvis Tool Analysis** (`jarvis-tool-analysis.json`)
- Total tool calls (24h)
- Success rate percentage
- Failed calls count
- Average execution time
- Tool call frequency (time series)
- Top 15 most used tools
- Slowest tools (avg execution time)
- Recent failed tool calls (raw logs)

---

## 📊 Sample Log Formats

### Tool Log Entry
```json
{
  "timestamp": "2025-11-24T00:19:23.835813",
  "mode": "cloud",
  "tool": "get_time",
  "arguments": {},
  "result": {
    "ok": true,
    "speech": "Good morning! It's 12:19 AM on Monday, November 24",
    "has_data": true,
    "error": null
  },
  "duration_ms": 213.71,
  "user_query": "What time is it?"
}
```

### LLM Log Entry
```json
{
  "timestamp": "2025-11-24T00:19:23.835813",
  "mode": "cloud",
  "provider": "xai",
  "model": "grok-4-fast-reasoning-latest",
  "prompt_type": "routing",
  "user_query": "What time is it?",
  "messages_count": 1,
  "response": {
    "type": "text",
    "text_preview": "It's 12:19 AM on Monday, November 24.",
    "tool_name": null,
    "has_thinking": false
  },
  "usage": {
    "input_tokens": 8168,
    "output_tokens": 13,
    "total_tokens": 8181,
    "cost_usd": 0.0016,
    "note": null
  },
  "duration_ms": 1801.73,
  "success": true,
  "error": null
}
```

---

## 🔍 Useful LogQL Queries

### LLM Queries

#### All LLM calls
```logql
{job="jarvis", log_type="llm"} | json
```

#### LLM calls by specific model
```logql
{job="jarvis", log_type="llm", model="grok-4-fast-reasoning-latest"} | json
```

#### LLM calls by provider
```logql
{job="jarvis", log_type="llm", provider="xai"} | json
```

#### Failed LLM calls
```logql
{job="jarvis", log_type="llm"} | json | success = "false"
```

#### Slow LLM calls (>2 seconds)
```logql
{job="jarvis", log_type="llm"} | json | duration_ms > 2000
```

#### Total cost in last 24 hours
```logql
sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h]))
```

#### Average response time by model
```logql
avg by (model) (avg_over_time({job="jarvis", log_type="llm"} | json | unwrap duration_ms [1h]))
```

#### Total tokens used
```logql
sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap total_tokens [24h]))
```

### Tool Queries

#### All tool calls
```logql
{job="jarvis", log_type="tools"} | json
```

#### Failed tool calls
```logql
{job="jarvis", log_type="tools"} | json | result_ok = "false"
```

#### Specific tool only
```logql
{job="jarvis", log_type="tools", tool_name="search_memory"} | json
```

#### Slow tools (>5 seconds)
```logql
{job="jarvis", log_type="tools"} | json | duration_ms > 5000
```

#### Success rate
```logql
sum(count_over_time({job="jarvis", log_type="tools"} | json | result_ok = "true" [1h])) / sum(count_over_time({job="jarvis", log_type="tools"} | json [1h]))
```

#### Top 10 most used tools
```logql
topk(10, sum by (tool_name) (count_over_time({job="jarvis", log_type="tools"} | json [24h])))
```

---

## 🎯 Use Cases

### 1. **Cost Monitoring**
- **Goal**: Track LLM API costs across providers
- **Dashboard**: Jarvis LLM Performance → "Total Cost (24h)" panel
- **Query**: `sum(sum_over_time({log_type="llm"} | json | unwrap cost_usd [24h]))`
- **Action**: Set up Prometheus alert if cost exceeds budget

### 2. **Performance Analysis**
- **Goal**: Compare response times between models
- **Dashboard**: Jarvis LLM Performance → "Response Time by Model" panel
- **Query**: `avg by (model) (avg_over_time({log_type="llm"} | json | unwrap duration_ms [5m]))`
- **Action**: Switch to faster model if needed

### 3. **Tool Debugging**
- **Goal**: Identify failing tools
- **Dashboard**: Jarvis Tool Analysis → "Recent Failed Tool Calls" panel
- **Query**: `{log_type="tools"} | json | result_ok = "false"`
- **Action**: Fix tool code or adjust parameters

### 4. **Usage Patterns**
- **Goal**: Understand which tools are used most
- **Dashboard**: Jarvis Tool Analysis → "Top 15 Most Used Tools" panel
- **Query**: `topk(15, sum by (tool_name) (count_over_time({log_type="tools"} | json [24h])))`
- **Action**: Optimize frequently-used tools

### 5. **Model Comparison**
- **Goal**: Evaluate xAI Grok vs Claude vs Ollama
- **Dashboard**: Jarvis LLM Performance → "Calls by Model" + "Response Time by Model"
- **Metrics**: Compare cost, speed, success rate
- **Action**: Choose optimal model for workload

---

## 🚀 Getting Started

### 1. **View Dashboards**
```bash
# Open Grafana
open http://localhost:3000

# Login
Username: admin
Password: jarvis_grafana_2025

# Navigate to Dashboards → Jarvis folder
```

### 2. **Generate Test Data**
```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate

# Run a few queries to generate logs
./orchestrator/orchestrator_v2.py cloud "What time is it?"
./orchestrator/orchestrator_v2.py cloud "search for bitcoin"
./orchestrator/orchestrator_v2.py cloud "remember my favorite food is pizza"

# Wait ~15 seconds for Promtail to ship logs
# Then refresh Grafana dashboards
```

### 3. **Explore Logs**
```bash
# In Grafana, click "Explore" (compass icon)
# Select "Loki" data source
# Enter query:
{job="jarvis", log_type="llm"} | json
```

---

## 📁 Files Modified/Created

### Created:
- `lib/llm_logger.py` - LLM call logger
- `monitoring/grafana/dashboards/jarvis-llm-performance.json` - LLM dashboard
- `monitoring/grafana/dashboards/jarvis-tool-analysis.json` - Tool dashboard
- `monitoring/LLM_LOGGING_IMPLEMENTATION.md` - This file

### Modified:
- `orchestrator/router_v2.py` - Added LLM logging integration
- `monitoring/promtail-config.yml` - Updated to parse both log types correctly

---

## 🔧 Configuration

### LLM Logger
- **Location**: `lib/llm_logger.py`
- **Log File**: `logs/llm-calls-YYYY-MM-DD.jsonl`
- **Rotation**: Daily (automatic)

### Tool Logger (existing)
- **Location**: `lib/tool_logger.py`
- **Log File**: `logs/tools/tool-calls-YYYY-MM-DD.jsonl`
- **Rotation**: Daily (automatic)

### Promtail
- **Config**: `monitoring/promtail-config.yml`
- **Watch Paths**:
  - `/var/log/jarvis/tools/tool-calls-*.jsonl` → `log_type="tools"`
  - `/var/log/jarvis/llm-calls-*.jsonl` → `log_type="llm"`

### Grafana
- **URL**: http://localhost:3000
- **Dashboards**: Auto-loaded from `monitoring/grafana/dashboards/`
- **Data Source**: Loki (auto-provisioned)

---

## ⚠️ Important Notes

### Environment Setup
**ALWAYS activate the Python virtual environment before running Jarvis:**
```bash
source ~/jarvis-venv/bin/activate
```

**NOT conda!** Use the venv:
- ✅ `source ~/jarvis-venv/bin/activate`
- ❌ `conda activate jarvis-voice`

### Log Shipping Delay
- Promtail ships logs in batches (default: every 1 second)
- Wait ~15 seconds after running Jarvis before querying Grafana
- Use `docker logs jarvis-promtail` to verify log shipping

### Query Performance
- Use time ranges to avoid scanning all data
- Filter by labels (`log_type`, `model`, `tool_name`) before parsing JSON
- Example: `{log_type="llm", model="grok-4-fast-reasoning-latest"} | json`

---

## 🔮 Future Enhancements

### Planned (Not Yet Implemented):

1. **Prometheus Metrics Endpoint**
   - Expose `/metrics` in Jarvis API
   - Track request rates, latency, errors
   - Monitor memory/CPU usage

2. **Alerting**
   - Email/Slack notifications for high costs
   - Alert on tool failure spikes
   - Notify when response times exceed thresholds

3. **Historical Analysis**
   - Compare model performance week-over-week
   - Track cost trends
   - Identify usage patterns

4. **Advanced Dashboards**
   - User query analysis (most common requests)
   - Multi-turn conversation tracking
   - OpenCode integration metrics

---

## ✅ Testing Checklist

- [x] LLM logger created and integrated
- [x] Router logs all LLM calls
- [x] Promtail ships logs to Loki
- [x] Grafana queries work (tool and LLM logs)
- [x] Dashboards load and display data
- [x] Log format matches Promtail parser
- [x] Labels correctly extracted
- [ ] API metrics endpoint (future)

---

**Status**: ✅ **FULLY OPERATIONAL**

LLM logging is now capturing all API calls, costs, and performance metrics. Grafana dashboards provide real-time visibility into Jarvis operations.

---

**Access Grafana**: http://localhost:3000 (admin / jarvis_grafana_2025)

