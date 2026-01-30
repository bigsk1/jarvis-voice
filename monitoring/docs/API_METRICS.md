# Jarvis API Metrics

## 🎯 Overview

The Jarvis API now exposes Prometheus metrics at `/metrics` endpoint, providing real-time observability into API performance, request rates, and errors.

---

## ✅ What Was Added

### 1. **Prometheus Instrumentator**
- Installed `prometheus-fastapi-instrumentator` library
- Automatically instruments all FastAPI endpoints
- Provides standard HTTP metrics + custom Jarvis metrics

### 2. **Metrics Endpoint**
- **URL**: `http://localhost:8880/metrics`
- **Format**: Prometheus text format
- **Access**: Public (no authentication)
- **Excluded from instrumentation**: `/metrics`, `/docs`, `/redoc`, `/openapi.json`

### 3. **Prometheus Scraping**
- Updated `monitoring/prometheus.yml`
- Job: `jarvis_api`
- Target: `localhost:8880`
- Scrape interval: 15 seconds

---

## 📊 Available Metrics

### **Standard HTTP Metrics**

#### Request Count
```
http_requests_total{method="POST", handler="/api/alerts", status="200"}
```
- **Description**: Total number of HTTP requests
- **Labels**: `method`, `handler`, `status`
- **Type**: Counter

#### Request Duration
```
http_request_duration_seconds{method="POST", handler="/api/alerts"}
```
- **Description**: HTTP request latency (in seconds)
- **Labels**: `method`, `handler`
- **Type**: Histogram
- **Buckets**: 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, INF

#### Requests In Progress
```
jarvis_api_requests_inprogress{method="POST", handler="/api/alerts"}
```
- **Description**: Number of HTTP requests currently being processed
- **Labels**: `method`, `handler`
- **Type**: Gauge

#### Request Size
```
http_request_size_bytes{method="POST", handler="/api/alerts"}
```
- **Description**: HTTP request body size (in bytes)
- **Type**: Summary

#### Response Size
```
http_response_size_bytes{method="POST", handler="/api/alerts"}
```
- **Description**: HTTP response body size (in bytes)
- **Type**: Summary

---

## 🔍 Useful Prometheus Queries

### Request Rate (per second)
```promql
rate(http_requests_total{job="jarvis_api"}[5m])
```

### Average Response Time
```promql
rate(http_request_duration_seconds_sum{job="jarvis_api"}[5m]) / 
rate(http_request_duration_seconds_count{job="jarvis_api"}[5m])
```

### 95th Percentile Response Time
```promql
histogram_quantile(0.95, 
  rate(http_request_duration_seconds_bucket{job="jarvis_api"}[5m])
)
```

### Error Rate (4xx/5xx)
```promql
sum(rate(http_requests_total{job="jarvis_api", status=~"4..|5.."}[5m]))
```

### Requests by Endpoint
```promql
sum by (handler) (rate(http_requests_total{job="jarvis_api"}[5m]))
```

### Concurrent Requests
```promql
jarvis_api_requests_inprogress{job="jarvis_api"}
```

---

## 🚀 Usage

### 1. **Start the API**
```bash
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate

# Cloud mode
./bin/jarvis-api

# OR Local mode
./bin/jarvis-api --local
```

You should see:
```
✅ Prometheus metrics enabled at /metrics
📡 Starting API server...
   Mode: cloud
   Port: 8880
   Docs: http://localhost:8880/docs
```

### 2. **Verify Metrics Endpoint**
```bash
curl http://localhost:8880/metrics
```

Expected output (sample):
```
# HELP http_requests_total Total number of HTTP requests
# TYPE http_requests_total counter
http_requests_total{handler="/",method="GET",status="200"} 5.0

# HELP http_request_duration_seconds HTTP request latency
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{handler="/api/health",le="0.005",method="GET"} 10.0
http_request_duration_seconds_bucket{handler="/api/health",le="0.01",method="GET"} 10.0
...
```

### 3. **Check Prometheus**
```bash
# Open Prometheus UI
open http://localhost:9090

# Go to Status → Targets
# Look for "jarvis_api" - should show "UP"
```

### 4. **View in Grafana**
```bash
# Open Grafana
open http://localhost:3000

# Go to Explore
# Select Prometheus data source
# Query: rate(http_requests_total{job="jarvis_api"}[5m])
```

---

## 📈 Grafana Dashboard

You can create a custom dashboard for API metrics with panels like:

### **API Request Rate**
- Query: `sum(rate(http_requests_total{job="jarvis_api"}[5m]))`
- Visualization: Time series graph

### **Response Time by Endpoint**
- Query: `avg by (handler) (rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m]))`
- Visualization: Table or bar chart

### **Error Rate**
- Query: `sum(rate(http_requests_total{job="jarvis_api", status=~"5.."}[5m]))`
- Visualization: Stat panel with threshold (red if >0)

### **Requests by Status Code**
- Query: `sum by (status) (rate(http_requests_total{job="jarvis_api"}[5m]))`
- Visualization: Pie chart or stacked bar chart

---

## 🧪 Testing

### Generate Some Traffic
```bash
# Health check
curl http://localhost:8880/api/health

# Root endpoint
curl http://localhost:8880/

# Status endpoint
curl http://localhost:8880/api/status

# Alert (test)
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Alert",
    "message": "This is a test",
    "priority": "normal"
  }'
```

### Check Metrics
```bash
# View raw metrics
curl http://localhost:8880/metrics | grep http_requests_total

# Check Prometheus (after 15 seconds)
curl -s 'http://localhost:9090/api/v1/query?query=http_requests_total{job="jarvis_api"}' | jq .
```

---

## 🔧 Configuration

### Enable/Disable Metrics
Metrics are **always enabled** if the `prometheus-fastapi-instrumentator` library is installed. There is no environment variable to disable them.

To disable metrics, you would need to uninstall the library:
```bash
pip uninstall prometheus-fastapi-instrumentator
```

However, this is not recommended - the metrics have minimal overhead and provide valuable insights.

### Custom Metrics (Future Enhancement)
You can add custom metrics in `api/server.py`:

```python
from prometheus_client import Counter, Histogram, Gauge

# Custom counter
alerts_sent = Counter('jarvis_alerts_sent_total', 'Total alerts sent')

# Custom gauge
active_reminders = Gauge('jarvis_active_reminders', 'Number of active reminders')

# In your route handler:
@app.post("/api/alerts")
async def create_alert(...):
    alerts_sent.inc()
    # ... rest of your code
```

---

## 📊 Metrics Summary

| Metric | Type | Description |
|--------|------|-------------|
| `http_requests_total` | Counter | Total requests by endpoint/method/status |
| `http_request_duration_seconds` | Histogram | Request latency distribution |
| `jarvis_api_requests_inprogress` | Gauge | Current concurrent requests |
| `http_request_size_bytes` | Summary | Request body sizes |
| `http_response_size_bytes` | Summary | Response body sizes |
| `process_resident_memory_bytes` | Gauge | Process memory usage |
| `process_cpu_seconds_total` | Counter | CPU time used |
| `process_open_fds` | Gauge | Open file descriptors |

---

## ⚠️ Important Notes

### API Port
- **Port**: 8880 (NOT 8091!)
- Updated in `monitoring/prometheus.yml`
- Prometheus scrapes `localhost:8880/metrics`

### Virtual Environment
Always activate the venv before starting the API:
```bash
source ~/jarvis-venv/bin/activate
./bin/jarvis-api
```


---

## 🐛 Troubleshooting

### "Metrics not showing in Prometheus"
1. Check API is running: `curl http://localhost:8880/metrics`
2. Check Prometheus targets: http://localhost:9090/targets
3. Verify port is correct (8880, not 8091)

### "Module 'prometheus_fastapi_instrumentator' not found"
```bash
source ~/jarvis-venv/bin/activate
pip install prometheus-fastapi-instrumentator
```

### "Metrics endpoint returns 404"
- Make sure you're running the updated `api/server.py`
- Check the startup message shows: "✅ Prometheus metrics enabled at /metrics"

---

## ✅ Checklist

- [x] Installed `prometheus-fastapi-instrumentator`
- [x] Updated `api/server.py` to expose `/metrics`
- [x] Updated `requirements.txt`
- [x] Fixed Prometheus port (8091 → 8880)
- [x] Reloaded Prometheus configuration
- [ ] Started API and verified metrics work
- [ ] Created Grafana dashboard for API metrics (future)

---

## 🔮 Future Enhancements

1. **Custom Business Metrics**:
   - `jarvis_alerts_sent_total` - Track alerts sent
   - `jarvis_reminders_triggered_total` - Track reminders
   - `jarvis_voice_commands_total` - Track TTS usage

2. **Grafana Dashboard**:
   - Create "Jarvis API Performance" dashboard
   - Include request rate, latency, errors
   - Add alerting for high error rates

3. **Alerting**:
   - Alert on high API error rate
   - Alert on slow response times
   - Alert on API downtime

---

**Status**: ✅ **IMPLEMENTED AND READY TO TEST**

Start the API with `./bin/jarvis-api` and verify metrics at http://localhost:8880/metrics

**Next Step**: Start the API to generate metrics!

