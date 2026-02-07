# Jarvis Monitoring Stack - Deployment Summary

## 🎉 What's Been Built

A complete, self-hosted observability stack for Jarvis Voice Assistant

---

## 📦 Components

### **1. Grafana** (Port 3000)
- **Purpose**: Visualization and dashboards
- **Access**: http://localhost:3000
- **Credentials**: `admin` / `jarvis_grafana_2025`
- **Features**:
  - Pre-built "Jarvis Overview" dashboard
  - Real-time log exploration
  - Custom query builder

### **2. Loki** (Port 3100)
- **Purpose**: Log aggregation and storage
- **Features**:
  - 30-day log retention
  - Full-text search with BM25 ranking
  - JSON log parsing
  - Label-based indexing

### **3. Promtail**
- **Purpose**: Log shipping agent
- **Watches**:
  - `logs/tools/tool-calls-*.jsonl` → Tool execution logs
  - `logs/llm-calls-*.jsonl` → LLM API calls
  - `logs/opencode-*.log` → OpenCode activity
- **Features**:
  - Automatic JSON field extraction
  - Label injection (tool_name, status, model, provider)
  - Real-time log tailing

### **4. Prometheus** (Port 9090)
- **Purpose**: Metrics collection and alerting
- **Scrapes**:
  - Mini-AI Ollama (localhost:11434)
  - (Future) Jarvis API metrics endpoint
- **Features**:
  - Alert rules for service degradation
  - Performance monitoring
  - Custom metric queries

---

## 📊 What You Can Monitor

### **Tool Analytics**
- ✅ Success/failure rates per tool
- ✅ Execution duration (find slow tools)
- ✅ Error messages and patterns
- ✅ Most frequently used tools
- ✅ Tool call timeline (when things happened)

### **LLM Performance**
- ✅ Response times per model (Grok, Claude, Qwen, etc.)
- ✅ Token usage and cost tracking
- ✅ Provider comparison (xAI vs Anthropic vs Ollama)
- ✅ Cloud vs Local mode performance

### **Error Investigation**
- ✅ All failed tool calls with full error details
- ✅ Search errors by keyword (timeout, connection, etc.)
- ✅ Error frequency and trends
- ✅ Time-based error correlation

### **System Health**
- ✅ Ollama server availability (Mini-AI)
- ✅ Service uptime monitoring
- ⚠️ Alerts for critical failures (via Prometheus)

---

## 🚀 Quick Start

```bash
# Start all services
cd ~/jarvis-voice/monitoring
./manage.sh start

# Check status
./manage.sh status

# View logs
./manage.sh logs grafana
./manage.sh logs loki
./manage.sh logs promtail

# Restart services
./manage.sh restart

# Stop everything
./manage.sh stop

# Backup Grafana dashboards
./manage.sh backup
```

---

## 📖 Documentation

| Document | Purpose |
|----------|---------|
| **QUICKSTART.md** | 5-minute setup guide |
| **GRAFANA_LOG_ANALYSIS_GUIDE.md** | Deep dive into log analysis, advanced queries, real-world scenarios |
| **README.md** | Full technical documentation, architecture, configuration |
| **alerts.yml** | Prometheus alert rules (editable) |

---

## 🎯 Common Use Cases

### **1. "Why did this tool fail?"**
1. Open Grafana → Explore
2. Query: `{job="jarvis", log_type="tools"} | json | tool_name = "TOOL_NAME" | result_ok = "false"`
3. Click log entry to see full error message

### **2. "Which LLM model is fastest?"**
1. Open Grafana → Explore
2. Query: `avg by (model) (sum_over_time({log_type="llm"} | json | unwrap response_time_ms [24h]))`
3. Compare results

### **3. "What happened at 2pm yesterday?"**
1. Open Grafana → Explore
2. Query: `{job="jarvis"} | json`
3. Set time range to yesterday 14:00-15:00
4. View all tool calls and user queries

### **4. "How much am I spending on LLM tokens?"**
1. Open Grafana → Explore
2. Query: `sum(sum_over_time({log_type="llm"} | json | unwrap tokens_used [7d]))`
3. Calculate cost based on provider pricing

### **5. "Show me slow tool calls"**
1. Open Grafana → Explore
2. Query: `{job="jarvis", log_type="tools"} | json | duration_ms > 5000`
3. Identify performance bottlenecks

---

## 🔧 Configuration Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Service definitions, ports, volumes |
| `loki-config.yml` | Loki storage and retention settings |
| `promtail-config.yml` | Log file paths, parsing rules, label extraction |
| `prometheus.yml` | Scrape targets, intervals |
| `alerts.yml` | Alert rules (thresholds, notifications) |
| `grafana/provisioning/datasources/` | Auto-configured data sources |
| `grafana/provisioning/dashboards/` | Auto-loaded dashboards |

---

## 🎨 Dashboard Panels

The pre-built "Jarvis Overview" dashboard includes:

1. **Total Tool Calls (24h)** - Activity volume
2. **Tool Success Rate** - Overall health percentage
3. **Top 10 Most Used Tools** - Usage patterns
4. **Tool Call Timeline** - Visual activity graph
5. **Recent Errors** - Latest failures with details
6. **Tool Performance (Avg Duration)** - Identify slow tools
7. **LLM Response Times** - Model speed comparison
8. **LLM Token Usage** - Cost tracking by model

---

## 🔍 Advanced Features

### **LogQL Queries**
Loki uses LogQL (similar to PromQL) for querying logs:

```logql
# Basic search
{job="jarvis"} | json

# Filter by field
{job="jarvis"} | json | tool_name = "search_memory"

# Regex matching
{job="jarvis"} | json | result_error =~ "(?i)timeout"

# Numeric filtering
{job="jarvis"} | json | duration_ms > 5000

# Aggregations
sum by (tool_name) (count_over_time({job="jarvis"} | json [1h]))

# Average calculation
avg by (model) (sum_over_time({log_type="llm"} | json | unwrap response_time_ms [24h]))
```

See **GRAFANA_LOG_ANALYSIS_GUIDE.md** for 50+ example queries!

### **Prometheus Alerts**
Currently configured alerts:
- ✅ High tool failure rate (>30% failures for 5 min)
- ✅ Ollama server down (>2 min downtime)
- ✅ High memory usage (>4GB for 10 min)
- ✅ Slow tool execution (95th percentile >30s)
- ✅ High LLM response time (95th percentile >10s)
- ❌ n8n server down (REMOVED - n8n workflow disabled)

Edit `alerts.yml` to customize thresholds or add new alerts.

---

## 🛠️ Maintenance

### **Data Retention**
- **Loki**: 30 days (720 hours) - configured in `loki-config.yml`
- **Prometheus**: Based on disk space (typically 15 days default)
- **Grafana**: Dashboards persist indefinitely

### **Disk Space**
Monitor Docker volumes:
```bash
docker system df -v
```

Clean up old data:
```bash
# Prune old logs (WARNING: irreversible)
docker volume prune
```

### **Backups**
```bash
# Backup Grafana dashboards
cd ~/jarvis-voice/monitoring
./manage.sh backup

# Manual backup of all data
tar -czf monitoring-backup-$(date +%Y%m%d).tar.gz \
  -C ~ jarvis-voice/monitoring \
  --exclude='monitoring/prometheus-data/*' \
  --exclude='monitoring/loki-data/*'
```

### **Updates**
Update service versions in `docker-compose.yml`:
```yaml
services:
  grafana:
    image: grafana/grafana:10.2.3  # Change version here
```

Then:
```bash
./manage.sh restart
```

---

## 🐛 Troubleshooting

### **"No logs in Grafana"**
1. Check time range (top right) - set to "Last 24 hours"
2. Verify Promtail is watching logs:
   ```bash
   ./manage.sh logs promtail | grep "Watching"
   ```
3. Check log files exist:
   ```bash
   ls -lh ~/jarvis-voice/logs/tools/
   ```

### **Services Not Starting**
```bash
# Check Docker status
docker ps -a | grep jarvis

# View service logs
./manage.sh logs grafana
./manage.sh logs loki

# Restart everything
./manage.sh restart
```

### **High Disk Usage**
```bash
# Check volume sizes
docker system df -v

# Clean up (WARNING: deletes data)
docker volume prune
```

---

## 📈 Future Enhancements

### **Planned (Not Yet Implemented)**:
1. **Jarvis API Metrics Endpoint**
   - Expose `/metrics` in Jarvis API
   - Track request rates, latency, errors
   - Monitor memory/CPU usage

2. **Alerting via Email/Slack**
   - Configure Alertmanager
   - Email notifications for critical alerts
   - Slack webhooks for warnings

3. **System Metrics**
   - Add node_exporter for Fred system metrics
   - Monitor CPU, RAM, disk, network
   - Track resource usage over time

4. **Log Aggregation from Multiple Sources**
   - Jarvis on other machines
   - OpenCode workspace logs
   - System logs (auth, cron, etc.)

---

## 🎓 Learning Resources

- **Loki Documentation**: https://grafana.com/docs/loki/latest/
- **LogQL Guide**: https://grafana.com/docs/loki/latest/logql/
- **Prometheus Querying**: https://prometheus.io/docs/prometheus/latest/querying/basics/
- **Grafana Dashboards**: https://grafana.com/docs/grafana/latest/dashboards/

---

## ✅ Deployment Checklist

- [x] Docker Compose stack created
- [x] Grafana accessible at http://localhost:3000
- [x] Loki receiving logs from Promtail
- [x] Promtail watching Jarvis log files
- [x] Prometheus scraping Mini-AI Ollama
- [x] Pre-built dashboard deployed  
- [x] Alert rules configured
- [x] Documentation created
- [x] Management scripts functional
- [ ] API metrics endpoint (future)
- [ ] Email/Slack alerting (future)

---

**Status**: ✅ **FULLY OPERATIONAL**

All services running, logs flowing, dashboard accessible. Ready for deep-dive analysis!

---

**Access**: http://localhost:3000 (admin / jarvis_grafana_2025)

