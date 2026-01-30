# Jarvis Monitoring Stack

Complete observability solution for Jarvis Voice Assistant using **Grafana + Loki + Prometheus**.

## 🎯 What This Provides

- **📊 Real-time Dashboards** - Visualize tool calls, LLM usage, errors, performance
- **🔍 Log Aggregation** - Centralized search across all Jarvis logs
- **📈 Metrics & Alerts** - Track system health and get notified of issues
- **🕐 Historical Analysis** - 30 days of data retention for trend analysis

---

## 🏗️ Architecture

```
Fred (localhost) - Jarvis Host
├── Jarvis Voice Assistant
│   └── Logs → /home/boss/jarvis-voice/logs/
│       ├── tools/tool-calls-*.jsonl
│       ├── llm-calls-*.jsonl
│       └── opencode-*.log
├── Promtail (log shipper)
│   └── Ships logs → Loki
├── Loki (log storage)
│   └── Stores 30 days of logs
├── Prometheus (metrics)
│   └── Monitors:
│  
│       - Ollama (192.168.70.226:11434)
│       - Mini-AI n8n (192.168.70.226:5678)
│       - Mini-AI Qdrant (192.168.70.226:6333)
└── Grafana (visualization)
    └── Dashboards + Alerts
```

---

## 🚀 Quick Start

### 1. Start the Stack

```bash
cd ~/jarvis-voice/monitoring
docker-compose up -d
```

### 2. Check Services

```bash
# View logs
docker-compose logs -f

# Check status
docker-compose ps
```

### 3. Access Dashboards

Open in your browser:
- **Grafana**: http://localhost:3000
  - Username: `admin`
  - Password: `jarvis_grafana_2025`
- **Prometheus**: http://localhost:9090
- **Loki**: http://localhost:3100

### 4. View Jarvis Dashboard

1. Log into Grafana
2. Go to **Dashboards** → **Jarvis** folder
3. Open **"Jarvis Overview"** dashboard

---

## 📊 Available Dashboards

### Jarvis Overview (Pre-installed)
- Total tool calls (24h)
- Tool call timeline
- Success/failure rates
- Recent errors
- LLM model usage
- Top 10 most used tools
- Recent LLM calls

### Intelligence Layer Metrics

The intelligence layer exposes Prometheus metrics:

```promql
# Total experiences and insights
jarvis_intelligence_experiences_total{mode="cloud"}
jarvis_intelligence_insights_total{mode="cloud", constraint_type="positive"}
jarvis_intelligence_insights_total{mode="cloud", constraint_type="negative"}

# Average confidence
jarvis_intelligence_avg_confidence{mode="cloud"}

# Pending reflections (should be low)
jarvis_intelligence_pending_reflections{mode="cloud"}
```

### Create More Dashboards

Click **+ Create** → **Dashboard** in Grafana to build custom views.

---

## 🔍 Querying Logs (LogQL)

### Example Queries

**All tool errors:**
```
{job="jarvis", log_type="tools", status="error"} | json
```

**Search for specific tool:**
```
{job="jarvis", log_type="tools"} | json | tool_name="search_memory"
```

**Tool calls in last hour:**
```
{job="jarvis", log_type="tools"} | json | __timestamp__ > 1h
```

**LLM calls by model:**
```
{job="jarvis", log_type="llm"} | json | model="qwen2.5:7b"
```

**OpenCode errors:**
```
{job="jarvis", log_type="opencode"} | regexp "ERROR"
```

---

## 📈 Metrics Available

### Prometheus Targets

- `jarvis_api` - Jarvis API health (if /metrics endpoint added)
- `n8n` - n8n workflow engine on Mini-AI
- `qdrant` - Vector database on Mini-AI

### Query Metrics

Open Prometheus (http://localhost:9090) and try:

```promql

# CPU usage (if node_exporter installed)
rate(node_cpu_seconds_total[5m])
```

---

## 🔔 Setting Up Alerts

### Email Alerts (via n8n)

1. Create n8n workflow on Mini-AI:
   ```
   Webhook Trigger (/alert-receiver)
     ↓
   Filter by severity
     ↓
   Gmail → Send email
   ```

2. Add to Prometheus config:
   ```yaml
   alerting:
     alertmanagers:
       - static_configs:
           - targets: ['192.168.70.226:5678/webhook/alert-receiver']
   ```

3. Restart Prometheus:
   ```bash
   docker-compose restart prometheus
   ```

---

## 🛠️ Maintenance

### View Logs

```bash
cd ~/jarvis-voice/monitoring

# All services
docker-compose logs -f

# Specific service
docker-compose logs -f grafana
docker-compose logs -f loki
```

### Restart Services

```bash
# All services
docker-compose restart

# Specific service
docker-compose restart grafana
```

### Stop Everything

```bash
docker-compose down
```

### Update Stack

```bash
docker-compose pull
docker-compose up -d
```

### Backup Data

```bash
# Backup volumes
docker run --rm \
  -v monitoring_grafana-data:/data \
  -v $(pwd):/backup \
  busybox tar czf /backup/grafana-backup-$(date +%Y%m%d).tar.gz /data

docker run --rm \
  -v monitoring_loki-data:/data \
  -v $(pwd):/backup \
  busybox tar czf /backup/loki-backup-$(date +%Y%m%d).tar.gz /data
```

---

## 🐛 Troubleshooting

### Logs Not Appearing

1. Check Promtail is running:
   ```bash
   docker-compose logs promtail
   ```

2. Verify log files exist:
   ```bash
   ls -la ../logs/tools/
   ```

3. Test Loki connection:
   ```bash
   curl http://localhost:3100/ready
   ```

### Grafana Login Issues

1. Reset admin password:
   ```bash
   docker-compose exec grafana grafana-cli admin reset-admin-password jarvis_grafana_2025
   ```

### Prometheus Not Scraping

1. Check targets in Prometheus:
   - Go to http://localhost:9090/targets
   - Look for red/down targets



### High Disk Usage

1. Check volume sizes:
   ```bash
   docker system df -v
   ```

2. Reduce retention in `loki-config.yml`:
   ```yaml
   limits_config:
     retention_period: 168h  # 7 days instead of 30
   ```

3. Restart Loki:
   ```bash
   docker-compose restart loki
   ```

---

## 🔗 Integration with n8n

### Send Events from Jarvis to n8n

Add webhook calls in `orchestrator/executor.py`:

```python
import requests

def _send_monitoring_event(event_type, data):
    try:
        requests.post(
            "http://192.168.70.226:5678/webhook/jarvis-monitoring",
            json={
                "event_type": event_type,
                "timestamp": datetime.now().isoformat(),
                "host": "fred",
                "data": data
            },
            timeout=5
        )
    except:
        pass  # Silent fail
```

### n8n Workflow Ideas

1. **Weekly Report**:
   - Query Grafana API for stats
   - Generate summary with AI
   - Email report

2. **Error Alerts**:
   - Receive webhook from Prometheus
   - Send Telegram/Email notification

3. **Intel Auto-Generation**:
   - Daily schedule
   - Analyze logs
   - Create intel files

---

## 📚 Resources

- [Grafana Documentation](https://grafana.com/docs/)
- [Loki LogQL](https://grafana.com/docs/loki/latest/logql/)
- [Prometheus Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Docker Compose Reference](https://docs.docker.com/compose/)

---

## 💬 Support

Issues? Questions?
- Check Grafana at http://localhost:3000
- View logs: `docker-compose logs -f`
- Restart services: `docker-compose restart`

---

**Last Updated**: 2025-11-23
**Version**: 1.0.0

