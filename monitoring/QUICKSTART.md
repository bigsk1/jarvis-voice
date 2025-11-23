# 🚀 Jarvis Monitoring - Quick Start

Get your monitoring stack up and running in **5 minutes**!

---

## ✅ Step 1: Start the Stack

```bash
cd ~/jarvis-voice/monitoring
./manage.sh start
```

**Expected output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Starting Jarvis Monitoring Stack
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Docker and Docker Compose are installed
ℹ  Starting containers...
✓ Services started successfully!

Access Grafana at: http://192.168.70.228:3000
Username: admin
Password: jarvis_grafana_2025
```

---

## 🌐 Step 2: Open Grafana

1. Open browser: **http://192.168.70.228:3000**
2. Login:
   

---

## 📊 Step 3: View Dashboard

1. Click **Dashboards** (left sidebar)
2. Click **Jarvis** folder
3. Open **"Jarvis Overview"** dashboard

You should see:
- Total tool calls (24h)
- Tool call timeline
- Success/failure rates
- Recent errors
- LLM model usage
- Top 10 tools

---

## 🔍 Step 4: Search Logs

1. Click **Explore** (compass icon, left sidebar)
2. Select **Loki** datasource (top dropdown)
3. Try these queries:

### All tool errors:
```
{job="jarvis", log_type="tools", status="error"} | json
```

### Search for specific tool:
```
{job="jarvis", log_type="tools"} | json | tool_name="search_memory"
```

### LLM calls by model:
```
{job="jarvis", log_type="llm"} | json | model="qwen3:14b"
```



---

## 🛠️ Management Commands

```bash
cd ~/jarvis-voice/monitoring

# View status
./manage.sh status

# View logs
./manage.sh logs           # All services
./manage.sh logs grafana   # Specific service

# Restart
./manage.sh restart

# Stop
./manage.sh stop

# Backup data
./manage.sh backup

# Show help
./manage.sh help
```

---

## 📈 What to Monitor

### First Week
- Watch tool success rates
- Identify most-used tools
- Look for error patterns

### After Tuning
- Compare model performance (cloud vs local)
- Track response times
- Analyze memory search patterns

---

## 🎓 Next Steps

1. **Create Custom Dashboard**:
   - Grafana → + Create → Dashboard
   - Add panels for your specific needs

2. **Set Up Alerts**:
   - Create n8n workflow for email/Slack alerts
   - Configure alert rules in Prometheus

3. **Deep Dive into Logs**:
   - See the comprehensive **[Grafana Log Analysis Guide](./GRAFANA_LOG_ANALYSIS_GUIDE.md)**
   - Learn advanced LogQL queries for troubleshooting
   - Create custom dashboards for your needs

---

## 💡 Pro Tips

### Find Slow Tools
```
topk(10, avg by (tool_name) ({job="jarvis", log_type="tools"} | json | unwrap duration_ms))
```

### Compare Models
```
{job="jarvis", log_type="llm"} | json | model=~"qwen.*"
```

### Track Memory Searches
```
{job="jarvis", log_type="memory"} | json | search_type="semantic"
```

---

## 🐛 Troubleshooting

### No Logs Appearing?

1. Check Jarvis is logging:
   ```bash
   ls -la ../logs/tools/
   ```

2. Check Promtail:
   ```bash
   ./manage.sh logs promtail
   ```

### Can't Access Grafana?

```bash
# Check service status
./manage.sh status

# Restart if needed
./manage.sh restart grafana
```

### Forgot Password?

```bash
docker exec -it jarvis-grafana grafana-cli admin reset-admin-password jarvis_grafana_2025
```

---

## 📞 Need Help?

- Check main README: `./README.md`
- View service logs: `./manage.sh logs`
- Restart everything: `./manage.sh restart`

---

**Ready?** Run `./manage.sh start` and open Grafana! 🎉

