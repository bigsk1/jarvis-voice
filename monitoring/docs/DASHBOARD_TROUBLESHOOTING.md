# Grafana Dashboard Troubleshooting

## 🚨 "No Data" in Dashboards

If you see "No data" in the Jarvis LLM Performance or Tool Analysis dashboards, follow these steps:

### **COMMON CAUSE: Dashboard Query Type Mismatch** ⭐

**The Fix (Already Applied)**:  
The original dashboards had Stat panels using `queryType: "range"` instead of `queryType: "instant"`. This has been fixed!

If you still see "No data", follow the steps below:

### **Step 1: Verify Loki Has Data**

```bash
# Check if Loki has tool logs
curl -s -G 'http://localhost:3100/loki/api/v1/query' \
  --data-urlencode 'query=sum(count_over_time({job="jarvis", log_type="tools"} | json [24h]))' \
  --data-urlencode 'time='$(date +%s)'' | jq '.data.result[0].value[1]'

# Check if Loki has LLM logs
curl -s -G 'http://localhost:3100/loki/api/v1/query' \
  --data-urlencode 'query=sum(count_over_time({job="jarvis", log_type="llm"} | json [24h]))' \
  --data-urlencode 'time='$(date +%s)'' | jq '.data.result[0].value[1]'
```

**Expected**: You should see a number (e.g., "1529")  
**If you see "null" or error**: Logs aren't reaching Loki - see "Logs Not Reaching Loki" section below

---

### **Step 2: Check Dashboard Time Range**

1. Open Grafana: http://localhost:3000
2. Open the dashboard showing "No data"
3. Look at top-right corner - time range selector
4. Try changing to: **Last 24 hours** or **Last 7 days**

**Common issue**: Dashboard might be set to "Last 15 minutes" but logs are older

---

###**Step 3: Check Dashboard Query**

1. Click on a panel showing "No data"
2. Click the **Edit** button (pencil icon)
3. Look at the **Query** field
4. Click **Run queries** button (circular arrow)

**Common issues**:
- Query uses `$__range` variable incorrectly
- Query references wrong labels (`job`, `log_type`)
- Data source not set to "Loki"

---

### **Step 4: Fix Dashboard Queries Manually**

If Step 3 shows errors, edit the query:

**For Tool Analysis panels**:
```logql
# Total Tool Calls
sum(count_over_time({job="jarvis", log_type="tools"} | json [24h]))

# Success Rate
sum(count_over_time({job="jarvis", log_type="tools"} | json | result_ok = "true" [24h])) / 
sum(count_over_time({job="jarvis", log_type="tools"} | json [24h]))

# Top 10 Tools
topk(10, sum by (tool_name) (count_over_time({job="jarvis", log_type="tools"} | json [24h])))
```

**For LLM Performance panels**:
```logql
# Total LLM Calls
sum(count_over_time({job="jarvis", log_type="llm"} | json [24h]))

# Total Cost
sum(sum_over_time({job="jarvis", log_type="llm"} | json | unwrap cost_usd [24h]))

# Average Response Time
avg(avg_over_time({job="jarvis", log_type="llm"} | json | unwrap duration_ms [24h]))
```

---

## 🔧 Logs Not Reaching Loki

If Step 1 shows no data, logs aren't being shipped to Loki.

### **Check 1: Are Logs Being Created?**

```bash
# Check if log files exist and are being written
ls -lh ~/jarvis-voice/logs/tools/tool-calls-*.jsonl
ls -lh ~/jarvis-voice/logs/llm-calls-*.jsonl

# See latest log entry
tail -1 ~/jarvis-voice/logs/tools/tool-calls-$(date +%Y-%m-%d).jsonl | jq .
tail -1 ~/jarvis-voice/logs/llm-calls-$(date +%Y-%m-%d).jsonl | jq .
```

**Expected**: Files exist and have recent timestamps  
**If missing**: Run Jarvis to generate logs

---

### **Check 2: Is Promtail Running?**

```bash
cd ~/jarvis-voice/monitoring
./manage.sh status | grep promtail
```

**Expected**: `Up X hours (healthy)`  
**If not running**: `./manage.sh restart`

---

### **Check 3: Is Promtail Watching the Log Files?**

```bash
docker logs jarvis-promtail 2>&1 | grep "tail routine: started"
```

**Expected**: You should see lines like:
```
tail routine: started path=/var/log/jarvis/tools/tool-calls-2025-11-24.jsonl
tail routine: started path=/var/log/jarvis/llm-calls-2025-11-24.jsonl
```

**If missing**: Promtail isn't finding the files - check volume mounts

---

### **Check 4: Are Logs Being Shipped?**

```bash
# Check Promtail logs for shipping activity
docker logs jarvis-promtail 2>&1 | tail -50 | grep -E "(POST|Successful)"
```

**Expected**: You should see POST requests to Loki  
**If missing**: Check `monitoring/promtail-config.yml` configuration

---

### **Check 5: Can Promtail Reach Loki?**

```bash
docker exec jarvis-promtail wget -O- http://loki:3100/ready
```

**Expected**: `ready`  
**If fails**: Network issue between containers

---

## 🔄 Fresh Start (Nuclear Option)

If nothing else works, restart the entire monitoring stack:

```bash
cd ~/jarvis-voice/monitoring

# Stop everything
./manage.sh stop

# Remove all data (WARNING: deletes existing logs/metrics)
sudo rm -rf loki-data/ prometheus-data/

# Start fresh
./manage.sh start

# Run Jarvis to generate new logs
cd ~/jarvis-voice
source ~/jarvis-venv/bin/activate
./orchestrator/orchestrator_v2.py cloud "test query"

# Wait 30 seconds for logs to be shipped
sleep 30

# Check Grafana dashboards
open http://localhost:3000
```

---

## 📊 API Performance Dashboard "No Data"

The API Performance dashboard uses **Prometheus** (not Loki), so different troubleshooting:

### **Check 1: Is API Running and Exposing /metrics?**

```bash
curl http://localhost:8880/metrics | head -20
```

**Expected**: You should see Prometheus metrics  
**If 404**: API isn't running or metrics not enabled

---

### **Check 2: Is Prometheus Scraping the API?**

```bash
# Check Prometheus targets
curl -s 'http://localhost:9090/api/v1/targets' | \
  jq '.data.activeTargets[] | select(.labels.job == "jarvis_api")'
```

**Expected**: `"health": "up"`  
**If "down"**: Prometheus can't reach the API - check port and network

---

### **Check 3: Does Prometheus Have Metrics?**

```bash
curl -s 'http://localhost:9090/api/v1/query?query=http_requests_total{job="jarvis_api"}' | \
  jq '.data.result'
```

**Expected**: Array with metric data  
**If empty**: Make some API requests first:
```bash
curl http://localhost:8880/
curl http://localhost:8880/api/health
curl http://localhost:8880/metrics

# Wait 15 seconds for Prometheus to scrape
sleep 15

# Try query again
```

---

## 🎯 Quick Diagnosis Commands

Run all checks at once:

```bash
cd ~/jarvis-voice

echo "=== LOGS STATUS ==="
echo "Tool logs: $(ls -1 logs/tools/tool-calls-*.jsonl 2>/dev/null | wc -l) files"
echo "LLM logs: $(ls -1 logs/llm-calls-*.jsonl 2>/dev/null | wc -l) files"

echo ""
echo "=== MONITORING STATUS ==="
cd monitoring
./manage.sh status | grep -E "(Up|Down)"

echo ""
echo "=== LOKI DATA ==="
curl -s -G 'http://localhost:3100/loki/api/v1/query' \
  --data-urlencode 'query=sum(count_over_time({job="jarvis"} | json [24h]))' | \
  jq '.data.result[0].value[1] // "No data"'

echo ""
echo "=== PROMETHEUS DATA ==="
curl -s 'http://localhost:9090/api/v1/query?query=up{job="jarvis_api"}' | \
  jq '.data.result[0].value[1] // "API not scraped"'
```

---

## 💡 Common Mistakes

1. **Wrong time range**: Dashboard set to "Last 15 minutes" but you ran Jarvis an hour ago
2. **Logs too old**: Promtail only ships NEW log entries (not existing ones)
3. **Case sensitivity**: `log_type="tools"` not `log_type="Tools"`
4. **Wrong data source**: Using Prometheus for logs or Loki for metrics
5. **$__range variable**: Not supported in all query types - use fixed `[24h]` instead

---

## 📞 Still Stuck?

1. Check all services are running: `cd monitoring && ./manage.sh status`
2. Look at service logs: `./manage.sh logs loki`, `./manage.sh logs promtail`
3. Verify network connectivity between containers
4. Check file permissions on log directories
5. Ensure clocks are synchronized (Loki is time-sensitive)

---

**Last Updated**: 2025-11-24  
**Jarvis Version**: 2.0 (with LLM logging + API metrics)

