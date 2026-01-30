# Grafana Log Analysis Guide for Jarvis

## Quick Access

**Grafana URL**: http://localhost:3000  
**Username**: `admin`  
**Password**: `jarvis_grafana_2025`

---

## 🎯 What You Can Analyze

### 1. **Tool Call Analytics**
- Success/failure rates per tool
- Execution times and performance
- Error patterns
- Most used tools
- Tool call frequency over time

### 2. **LLM Performance**
- Response times per model
- Token usage patterns
- Provider comparison (xAI, Anthropic, Ollama)
- Cloud vs Local mode performance

### 3. **Error Investigation**
- Failed tool calls with full error messages
- Error frequency by tool
- Time-based error patterns

### 4. **OpenCode Activity**
- Project creations
- Execution logs
- Build/test results

---

## 📊 Using the Pre-Built Dashboard

### Access the Dashboard:
1. Open Grafana: http://localhost:3000
2. Login with credentials above
3. Go to **Dashboards** → **Jarvis Overview**

### Dashboard Panels:
- **Total Tool Calls (24h)**: High-level activity
- **Tool Success Rate**: Overall health percentage
- **Top 10 Most Used Tools**: Usage patterns
- **Tool Call Timeline**: Activity over time
- **Recent Errors**: Last failures with details
- **Tool Performance (Avg Duration)**: Slowest tools
- **LLM Response Times**: Model performance
- **LLM Token Usage**: Cost tracking

---

## 🔍 Deep Dive Queries (Explore Tab)

### How to Use Explore:
1. Click **Explore** (compass icon) in left sidebar
2. Select **Loki** as data source
3. Enter LogQL queries below

### Essential Queries:

#### **1. All Tool Calls Today**
```logql
{job="jarvis", log_type="tools"} | json
```

#### **2. Failed Tool Calls Only**
```logql
{job="jarvis", log_type="tools"} | json | result_ok = "false"
```

#### **3. Specific Tool (e.g., search_memory)**
```logql
{job="jarvis", log_type="tools"} | json | tool_name = "search_memory"
```

#### **4. Slow Tool Calls (>5 seconds)**
```logql
{job="jarvis", log_type="tools"} | json | duration_ms > 5000
```

#### **5. Tool Calls by User Query**
```logql
{job="jarvis", log_type="tools"} | json | user_query != ""
```

#### **6. LLM Calls by Model**
```logql
{job="jarvis", log_type="llm"} | json | model = "claude-sonnet-4-5-20250929"
```

#### **7. LLM Calls by Provider**
```logql
{job="jarvis", log_type="llm"} | json | provider = "anthropic"
```

#### **8. High Token Usage (>10k tokens)**
```logql
{job="jarvis", log_type="llm"} | json | tokens_used > 10000
```

#### **9. OpenCode Logs**
```logql
{job="jarvis", log_type="opencode"}
```

#### **10. Errors Containing Specific Text**
```logql
{job="jarvis", log_type="tools"} | json | result_error =~ "(?i)timeout"
```

---

## 🎨 Advanced LogQL Techniques

### **Aggregations & Stats**

#### **Count Tool Calls per Tool (Last Hour)**
```logql
sum by (tool_name) (count_over_time({job="jarvis", log_type="tools"} | json [1h]))
```

#### **Average Duration per Tool**
```logql
avg by (tool_name) (
  sum_over_time({job="jarvis", log_type="tools"} | json | unwrap duration_ms [1h])
) / 
count by (tool_name) (count_over_time({job="jarvis", log_type="tools"} | json [1h]))
```

#### **Success Rate per Tool**
```logql
sum by (tool_name) (
  count_over_time({job="jarvis", log_type="tools"} | json | result_ok = "true" [1h])
) /
sum by (tool_name) (count_over_time({job="jarvis", log_type="tools"} | json [1h]))
```

#### **Token Usage by Model (Last 24h)**
```logql
sum by (model) (
  sum_over_time({job="jarvis", log_type="llm"} | json | unwrap tokens_used [24h])
)
```

### **Filtering & Pattern Matching**

#### **Find Tool Calls with Specific Argument**
```logql
{job="jarvis", log_type="tools"} | json | arguments =~ ".*search_term.*"
```

#### **Tools That Failed with "Connection" Errors**
```logql
{job="jarvis", log_type="tools"} | json | result_ok = "false" | result_error =~ "(?i)connection"
```

#### **LLM Calls Slower than 5 seconds**
```logql
{job="jarvis", log_type="llm"} | json | response_time_ms > 5000
```

---

## 🕵️ Real-World Investigation Scenarios

### **Scenario 1: "Why did this tool fail?"**

**Step 1**: Find the failure
```logql
{job="jarvis", log_type="tools"} | json | tool_name = "api_call" | result_ok = "false"
```

**Step 2**: Click on the log entry to see:
- Full error message (`result_error`)
- Arguments used (`arguments`)
- Timestamp (when it happened)
- Duration (if it timed out)

**Step 3**: Check if it's a pattern
```logql
{job="jarvis", log_type="tools"} | json | tool_name = "api_call" | result_ok = "false" | range 24h
```

### **Scenario 2: "Which LLM model is fastest?"**

**Query**:
```logql
avg by (model) (
  sum_over_time({job="jarvis", log_type="llm"} | json | unwrap response_time_ms [24h])
) /
count by (model) (count_over_time({job="jarvis", log_type="llm"} | json [24h]))
```

**Result**: Compare average response times for grok-4-fast-reasoning-latest, claude-sonnet-4-5, qwen3-vl, etc.

### **Scenario 3: "What was Jarvis doing at 2pm yesterday?"**

**Query**:
```logql
{job="jarvis", log_type="tools"} | json
```

**Then**: Adjust time range (top right) to "2025-11-22 14:00 to 2025-11-22 15:00"

**View**: All tool calls, user queries, and results from that hour

### **Scenario 4: "How much is Jarvis costing me in tokens?"**

**Total Tokens (Last 7 Days)**:
```logql
sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap tokens_used [7d]))
```

**By Provider**:
```logql
sum by (provider) (
  sum_over_time({job="jarvis", log_type="llm"} | json | unwrap tokens_used [7d])
)
```

**Estimated Cost** (if using xAI Grok at $0.20/1M input, $0.50/1M output):
- Find total tokens
- Assume 70% input, 30% output (typical ratio)
- Cost = (tokens * 0.7 * 0.20 / 1M) + (tokens * 0.3 * 0.50 / 1M)

### **Scenario 5: "Show me all failed OpenCode builds"**

**Query**:
```logql
{job="jarvis", log_type="opencode"} |~ "(?i)(error|failed|build.*failed)"
```

---

## 📈 Creating Custom Dashboards

### **1. Create a New Dashboard**:
1. Click **+** → **Dashboard**
2. Click **Add visualization**
3. Select **Loki** data source

### **2. Panel Types**:

#### **Time Series (Graph)**
- Best for: Tool call frequency, response times over time
- Query: `count_over_time({job="jarvis"} | json [5m])`

#### **Stat (Big Number)**
- Best for: Total counts, success rates
- Query: `count_over_time({job="jarvis"} | json [24h])`

#### **Table**
- Best for: Detailed log entries
- Query: `{job="jarvis"} | json`

#### **Bar Chart**
- Best for: Top N tools, comparing models
- Query: `sum by (tool_name) (count_over_time({job="jarvis"} | json [1h]))`

### **3. Pro Tips**:
- Use **Variables** for dynamic filtering (tool name, time range)
- Set **Auto-refresh** (e.g., every 30s) for live monitoring
- Use **Transformations** to format data (rename fields, join tables)
- Add **Annotations** to mark deployments or incidents

---

## 🚀 Performance Optimization

### **Query Performance Tips**:

1. **Use Time Ranges**: Don't query all-time data
   ```logql
   # Good
   {job="jarvis"} | json [24h]
   
   # Bad (slow)
   {job="jarvis"} | json
   ```

2. **Use Labels for Filtering** (faster than regex):
   ```logql
   # Good (uses label index)
   {log_type="tools"} | json | tool_name = "search_memory"
   
   # Slower (regex scan)
   {job="jarvis"} |~ "search_memory"
   ```

3. **Limit Results**:
   ```logql
   {job="jarvis"} | json | limit 100
   ```

4. **Use Aggregations** instead of returning raw logs when possible

---

## 🔧 Troubleshooting

### **"No logs volume available"**

**Cause**: Time range mismatch or Promtail not sending logs

**Fix**:
1. Check time range (top right): Set to "Last 24 hours"
2. Verify Promtail is running:
   ```bash
   cd ~/jarvis-voice/monitoring
   ./manage.sh status
   ```
3. Check Promtail logs:
   ```bash
   ./manage.sh logs promtail
   ```

### **"Parse error: syntax error"**

**Cause**: Invalid LogQL syntax

**Fix**: Common mistakes:
- Missing `| json` after log stream selector
- Using `=` instead of `=~` for regex
- Forgetting quotes around strings

### **Slow Query Performance**

**Fix**:
- Reduce time range
- Add more specific label filters
- Use `[5m]` or `[1h]` range vectors instead of instant queries
- Avoid `.*` regex patterns

---

## 📚 LogQL Cheat Sheet

| Operation | Syntax | Example |
|-----------|--------|---------|
| **Stream Selector** | `{label="value"}` | `{job="jarvis"}` |
| **Parse JSON** | `\| json` | `{job="jarvis"} \| json` |
| **Filter Field** | `\| field = "value"` | `\| tool_name = "search_memory"` |
| **Regex Match** | `\| field =~ "pattern"` | `\| result_error =~ "timeout"` |
| **Regex Not Match** | `\| field !~ "pattern"` | `\| tool_name !~ "mcp_.*"` |
| **Numeric Filter** | `\| field > 100` | `\| duration_ms > 5000` |
| **Count** | `count_over_time([range])` | `count_over_time([1h])` |
| **Sum** | `sum_over_time(\| unwrap field [range])` | `sum_over_time(\| unwrap tokens_used [24h])` |
| **Average** | `avg_over_time(\| unwrap field [range])` | `avg_over_time(\| unwrap duration_ms [1h])` |
| **Group By** | `sum by (label) (...)` | `sum by (tool_name) (count_over_time([1h]))` |
| **Line Contains** | `\|= "text"` | `\|= "error"` |
| **Line Not Contains** | `!= "text"` | `!= "success"` |
| **Limit Results** | `\| limit N` | `\| limit 50` |

---

## 🎓 Next Steps

1. **Explore the Dashboard**: Click through the pre-built "Jarvis Overview" dashboard
2. **Run Sample Queries**: Try the queries above in Explore tab
3. **Monitor in Real-Time**: Set auto-refresh and watch tool calls live
4. **Create Alerts**: Use Prometheus alerts (already configured in `alerts.yml`)
5. **Build Custom Dashboards**: Create panels for your specific use cases

---

## 📞 Quick Reference Commands

```bash
# View monitoring services
cd ~/jarvis-voice/monitoring
./manage.sh status

# Restart all services
./manage.sh restart

# View logs
./manage.sh logs loki
./manage.sh logs promtail
./manage.sh logs grafana

# Backup Grafana dashboards
./manage.sh backup

# Access Grafana
open http://localhost:3000
# Login: admin / jarvis_grafana_2025
```

---

**Happy Log Diving!** 🏊‍♂️📊

