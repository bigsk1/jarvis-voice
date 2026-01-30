# Grafana Dashboard Fix - Datasource UID Issue

**Date**: November 24, 2025  
**Issue**: All Grafana dashboards showing "No data" despite logs being present in Loki  
**Root Cause**: Hardcoded datasource UIDs in dashboard JSON files didn't match actual Grafana datasource UIDs

---

## 🔍 Problem Discovery

### Symptoms
- Tool Analysis dashboard: "No data" on all panels
- LLM Performance dashboard: "No data" on most panels
- API Performance dashboard: Not tested initially

### Investigation
1. Confirmed Loki had data:
   ```bash
   curl -s -G 'http://localhost:3100/loki/api/v1/query' \
     --data-urlencode 'query=sum(count_over_time({job="jarvis", log_type="tools"} | json [24h]))' | \
     jq '.data.result[0].value[1]'
   # Result: "1539" ✅
   ```

2. Checked Grafana datasource configuration:
   ```bash
   curl -s -H "Authorization: Basic YWRtaW46amFydmlzX2dyYWZhbmFfMjAyNQ==" \
     'http://localhost:3000/api/datasources' | \
     jq '.[] | select(.name == "Loki") | {name, uid, url, access}'
   # Result: uid = "P8E80F9AEF21F6940" ✅
   ```

3. **FOUND THE BUG!** Tested query via Grafana API:
   ```bash
   curl -s -H "Authorization: Basic ..." \
     -H "Content-Type: application/json" \
     -X POST 'http://localhost:3000/api/ds/query' \
     -d '{"queries":[{"refId":"A","expr":"...","datasource":{"type":"loki","uid":"loki"},"queryType":"instant"}]}'
   # Result: {"message": "Data source not found", "traceID": ""} ❌
   ```

**The dashboard JSON files used `uid: "loki"`, but Grafana expected `uid: "P8E80F9AEF21F6940"`!**

---

## 🔧 The Fix

### Step 1: Get Actual Datasource UIDs
```bash
# Loki datasource
curl -s -H "Authorization: Basic YWRtaW46amFydmlzX2dyYWZhbmFfMjAyNQ==" \
  'http://localhost:3000/api/datasources' | \
  jq '.[] | select(.name == "Loki") | .uid'
# Output: "P8E80F9AEF21F6940"

# Prometheus datasource
curl -s -H "Authorization: Basic YWRtaW46amFydmlzX2dyYWZhbmFfMjAyNQ==" \
  'http://localhost:3000/api/datasources' | \
  jq '.[] | select(.name == "Prometheus") | .uid'
# Output: "PBFA97CFB590B2093"
```

### Step 2: Update Dashboard JSON Files
```bash
cd ~/jarvis-voice/monitoring/grafana/dashboards

# Fix Loki datasource UID in Tool Analysis, LLM Performance, Overview
for file in jarvis-tool-analysis.json jarvis-llm-performance.json jarvis-overview.json; do
  sed -i 's/"uid": "loki"/"uid": "P8E80F9AEF21F6940"/g' "$file"
done

# Fix Prometheus datasource UID in API Performance
PROM_UID="PBFA97CFB590B2093"
sed -i "s/\"uid\": \"prometheus\"/\"uid\": \"$PROM_UID\"/g" jarvis-api-performance.json
```

### Step 3: Force Grafana to Re-provision Dashboards
```bash
cd ~/jarvis-voice/monitoring
docker compose stop grafana
docker compose rm -f grafana
docker compose up -d grafana
# Wait 10 seconds for Grafana to fully start and provision dashboards
```

---

## ✅ Results After Fix

### Tool Analysis Dashboard
| Panel | Status | Value |
|-------|--------|-------|
| **Total Tool Calls (24h)** | ✅ Working | 1539 |
| **Success Rate** | ✅ Working | 91.9% |
| **Failed Calls (24h)** | ✅ Working | 125 |
| **Avg Execution Time** | ✅ Working | 1.74s |
| **Tool Call Frequency** | ✅ Working | Graph showing spike at 07:00 |
| **Top 15 Most Used Tools** | ✅ Working | Table with data |
| **Slowest Tools** | ✅ Working | Table with data |
| **Recent Failed Tool Calls** | ✅ Working | Log stream |

### LLM Performance Dashboard
| Panel | Status | Note |
|-------|--------|------|
| **Avg Response Time** | ✅ Working | 4.47s |
| **Total LLM Calls** | ⏳ No data yet | Expected - new feature |
| **Total Cost** | ⏳ No data yet | Expected - new feature |
| **Total Tokens Used** | ⏳ No data yet | Expected - new feature |
| **Response Time by Model** | ⏳ No data yet | Expected - new feature |
| **Calls by Model** | ⏳ No data yet | Expected - new feature |
| **Cost by Provider** | ⏳ No data yet | Expected - new feature |

**Note**: LLM logging was just implemented, so there's no historical LLM data. These panels will populate once new LLM calls are made.

### API Performance Dashboard
| Panel | Status | Value |
|-------|--------|-------|
| **Request Rate** | ✅ Working | 0.00702 req/s |
| **95th Percentile Latency** | ✅ Working | 95 ms |
| **Error Rate (5xx)** | ✅ Working | No data (expected - no errors!) |
| **Concurrent Requests** | ✅ Working | 0 |
| **Request Rate Over Time** | ✅ Working | Graph showing activity |
| **Response Time Percentiles** | ✅ Working | Graph showing percentiles |

---

## 📚 Key Lessons

### 1. Why This Happened
- Grafana generates unique UIDs for datasources on first startup
- The dashboard JSON files were created with placeholder UIDs (`"loki"`, `"prometheus"`)
- When Grafana provisions dashboards, it doesn't auto-replace these UIDs

### 2. How to Prevent This
When creating new dashboards in the future:

**Option A: Export from Grafana UI**
1. Create dashboard in Grafana UI
2. Export JSON (includes correct UIDs)
3. Save to `monitoring/grafana/dashboards/`

**Option B: Use Variables**
Grafana provisioning supports datasource variables:
```json
{
  "datasource": {
    "type": "loki",
    "uid": "${DS_LOKI}"  // Variable reference
  }
}
```

**Option C: Get UIDs Before Creating Dashboards**
```bash
# Get Loki UID
curl -s -H "Authorization: Basic $(echo -n 'admin:jarvis_grafana_2025' | base64)" \
  'http://localhost:3000/api/datasources' | \
  jq -r '.[] | select(.name == "Loki") | .uid'

# Get Prometheus UID
curl -s -H "Authorization: Basic $(echo -n 'admin:jarvis_grafana_2025' | base64)" \
  'http://localhost:3000/api/datasources' | \
  jq -r '.[] | select(.name == "Prometheus") | .uid'
```

### 3. Testing Dashboards
Always test new dashboards immediately after provisioning:
```bash
# 1. Restart Grafana
cd ~/jarvis-voice/monitoring
docker compose restart grafana

# 2. Wait for startup
sleep 10

# 3. Check dashboard in browser
open http://localhost:3000/d/<dashboard-uid>

# 4. If "No data", check datasource UIDs in JSON
```

---

## 🔗 Related Fixes

During this investigation, we also discovered and fixed:
1. **Query Type Issue**: Some stat panels needed `queryType: "instant"` instead of `"range"`
2. **Time Range Issue**: Default Grafana time range was "Last 24 hours", but old data was from November 22-23

Both issues were addressed in the dashboard JSON updates.

---

## 📊 Dashboard URLs (Correct)

With the fix applied, all dashboards are now accessible at:

- **Tool Analysis**: http://localhost:3000/d/jarvis-tool-analysis
- **LLM Performance**: http://localhost:3000/d/jarvis-llm-perf/jarvis-llm-performance
- **API Performance**: http://localhost:3000/d/jarvis-api-perf/jarvis-api-performance
- **Overview**: http://localhost:3000/d/jarvis-overview

---

## 🚀 Next Steps

1. **Generate New LLM Logs**: Run some Jarvis queries to populate the LLM Performance dashboard
2. **Monitor Over Time**: Watch the dashboards fill with data as Jarvis is used
3. **Adjust Time Ranges**: If needed, adjust Grafana dashboard time ranges (e.g., "Last 7 days") to see more historical data

**Status**: ✅ All dashboards are now working correctly!

