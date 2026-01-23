# Alert Scenarios & Examples

Comprehensive examples for different alerting scenarios with Jarvis.

---

## 📋 Quick Reference

| Scenario | Auto-Resolve | Example File | Use Case |
|----------|--------------|--------------|----------|
| **Docker Containers** | ✅ Agent-based | `docker/monitor.py` | Remote servers |
| **URLs/APIs** | ✅ URL-based | `python/monitor_service.py` | Web services |
| **Systemd Services** | ✅ Agent-based | `python/process_monitor.py` | Local services |
| **Disk Space** | ✅ Agent-based | `python/disk_space_smart_monitor.py` | Server monitoring |
| **Security Cameras** | ❌ Manual | `python/ubiquiti_camera_webhook.py` | Person detection |
| **One-Time Events** | ❌ Manual | `bash/disk_space_monitor.sh` | Cron alerts |

---

## 🎯 Scenario 1: Docker Container Monitoring

**Use Case**: Monitor Docker containers on remote servers

**Auto-Resolve**: ✅ Yes - Agent detects when container comes back

**How it works**:
1. Container stops → Agent sends alert
2. Container starts → Agent resolves alert via API
3. Jarvis speaks: "Boss, good news! kokoro-cpu is back up and running"

**Files**:
- `docker/monitor.py` - Universal monitoring agent
- `docker/docker-compose.yml` - Easy deployment

**Deploy**:
```bash
cd ~/jarvis-monitor
docker-compose up -d
```

**Best for**:
- Remote servers (via Tailscale/WireGuard)
- Multiple containers
- Automated recovery notifications

---

## 🎯 Scenario 2: URL/API Health Monitoring

**Use Case**: Monitor web services, APIs, health endpoints

**Auto-Resolve**: ✅ Yes - Self-healing daemon checks URL

**How it works**:
1. URL down → Alert sent with `auto_resolve_url`
2. Self-healing daemon checks URL every 60s
3. URL up → Auto-resolves
4. Jarvis speaks: "Boss, good news! example.com is back up"

**Files**:
- `python/monitor_service.py` - URL monitoring script

**Example**:
```python
# Alert with auto-resolve URL
{
  "title": "API Down",
  "source": "monitor",
  "severity": "high",
  "auto_resolve_url": "https://api.example.com/health"  # ← Enables auto-resolve
}
```

**Best for**:
- Web applications
- REST APIs
- Services with health endpoints

---

## 🎯 Scenario 3: Systemd Service Monitoring

**Use Case**: Monitor local systemd services (nginx, postgresql, etc.)

**Auto-Resolve**: ✅ Yes - Agent detects when service restarts

**How it works**:
1. Service stops → Agent sends alert
2. Service starts → Agent resolves alert
3. Jarvis speaks: "Boss, good news! nginx is back up"

**Files**:
- `python/process_monitor.py` - Service/process monitor

**Configuration**:
```python
SERVICES_TO_MONITOR = [
    "nginx",
    "postgresql",
    "ollama",
]
```

**Deploy**:
```bash
# Run as systemd service
sudo cp process_monitor.service /etc/systemd/system/
sudo systemctl enable process_monitor
sudo systemctl start process_monitor
```

**Best for**:
- Critical system services
- Database servers
- Application services

---

## 🎯 Scenario 4: Disk Space Monitoring (Smart)

**Use Case**: Alert when disk space is low, auto-resolve when space is freed

**Auto-Resolve**: ✅ Yes - Agent checks disk space periodically

**How it works**:
1. Disk > 90% → Alert sent
2. Disk < 85% → Alert resolved
3. Prevents spam (only alerts on state change)

**Files**:
- `python/disk_space_smart_monitor.py` - Smart disk monitor

**Thresholds**:
```python
THRESHOLD_ALERT = 90    # Alert when > 90%
THRESHOLD_RESOLVE = 85  # Resolve when < 85%
```

**Best for**:
- Server disk monitoring
- Log partition monitoring
- Automated cleanup verification

---

## 🎯 Scenario 5: Security Camera Alerts (Ubiquiti)

**Use Case**: Alert when person detected by security camera

**Auto-Resolve**: ❌ No - Events are one-time

**How it works**:
1. Camera detects person → Webhook sent
2. Flask server receives webhook
3. Checks time window (e.g., 10PM-6AM)
4. Sends alert to Jarvis
5. Jarvis speaks: "Boss, person detected at Front Door Camera"

**Files**:
- `python/ubiquiti_camera_webhook.py` - Webhook handler

**Configuration**:
```python
ALERT_HOURS_START = 22  # 10 PM
ALERT_HOURS_END = 6     # 6 AM
```

**Deploy**:
```bash
python3 ubiquiti_camera_webhook.py
# Runs Flask server on port 5000

# In Ubiquiti: Add webhook
# http://YOUR_SERVER:5000/webhook
```

**Best for**:
- Home security
- After-hours monitoring
- Smart detection alerts

---

## 🎯 Scenario 6: One-Time Alerts (Cron Jobs)

**Use Case**: Simple alerts from bash scripts/cron jobs

**Auto-Resolve**: ❌ No - Manual acknowledgment

**How it works**:
1. Cron job runs check
2. Condition met → Send alert
3. Jarvis speaks alert
4. User manually clears: "Hey Jarvis, clear all alerts"

**Files**:
- `bash/disk_space_monitor.sh` - Simple cron alert

**Cron Setup**:
```bash
# Check disk space every 15 minutes
*/15 * * * * /path/to/disk_space_monitor.sh
```

**Best for**:
- Simple periodic checks
- Backup completion alerts
- Scheduled task notifications

---

## 🔧 Implementation Patterns

### Pattern 1: Agent-Based Auto-Resolve (Containers, Processes)

```python
# When service stops
send_alert("Service Stopped: nginx", ...)

# When service starts back up
resolve_alert_by_title("Service Stopped: nginx")
```

**Use when:**
- Only agent can check status (Docker API, systemctl, etc.)
- No URL to check remotely

### Pattern 2: URL-Based Auto-Resolve (Web Services)

```python
# When service is down
send_alert(
    "API Down",
    auto_resolve_url="https://api.example.com/health"  # ← Key!
)

# Self-healing daemon checks URL automatically
# No agent code needed for recovery
```

**Use when:**
- Service has HTTP health endpoint
- Jarvis can check URL remotely

### Pattern 3: Manual Acknowledgment (Events)

```python
# One-time event
send_alert("Person Detected: Front Door", ...)

# User manually clears
"Hey Jarvis, clear all alerts"
```

**Use when:**
- Events are one-time (not ongoing states)
- No "recovery" concept (camera detection, backup completion, etc.)

---

## 📊 Choosing the Right Pattern

```
Does the issue have a "resolved" state?
├─ No (one-time event) → Manual acknowledgment
└─ Yes → Continue

Can Jarvis check a URL?
├─ Yes → URL-based auto-resolve (easiest!)
└─ No → Continue

Can you run an agent where the resource is?
├─ Yes → Agent-based auto-resolve
└─ No → Manual acknowledgment
```

---

## 🚀 Quick Start Templates

### Template 1: New Monitoring Agent

```python
# 1. Check status
is_ok = check_something()

# 2. Track state
prev_status = last_status.get("my_thing")

# 3. State changed: down
if prev and not is_ok:
    send_alert("Thing Stopped: my_thing", ...)

# 4. State changed: up
elif prev == False and is_ok:
    resolve_alert_by_title("Thing Stopped: my_thing")

# 5. Update state
last_status["my_thing"] = is_ok
```

### Template 2: Webhook Handler

```python
from flask import Flask, request, jsonify

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    data = request.json
    
    # Extract info
    event_type = data.get('type')
    
    # Send to Jarvis
    requests.post(JARVIS_API, json={
        "title": f"Event: {event_type}",
        "source": "my-service",
        "severity": "medium"
    })
    
    return jsonify({"ok": True})
```

---

## 🔐 Security Considerations

### For Remote Monitoring

**Use Tailscale/WireGuard** (not port forwarding):
```bash
# Monitoring agent uses Tailscale IP
JARVIS_API: "http://100.101.102.103:8880/api/alerts"
```

### For Webhook Handlers

**Add API key authentication**:
```python
API_KEY = os.getenv("JARVIS_API_KEY")
headers = {"X-API-Key": API_KEY}
requests.post(JARVIS_API, json=alert, headers=headers)
```

**Or IP whitelist in nginx**:
```nginx
location /api/alerts {
    allow 192.168.1.0/24;  # Local network
    allow 100.0.0.0/8;     # Tailscale
    deny all;
}
```

---

## 📚 Complete Example Collection

```
code-examples/
├── python/
│   ├── ubiquiti_camera_webhook.py        - Camera webhooks
│   ├── process_monitor.py                - Service monitoring
│   ├── disk_space_smart_monitor.py       - Disk monitoring
│   ├── monitor_service.py               - URL monitoring
│   ├── docker_container_monitor.py      - Container monitoring
│   └── basic_alert.py                   - Simple alert
├── docker/
│   ├── monitor.py                       - Universal agent
│   ├── Dockerfile                       - Container build
│   └── docker-compose.yml               - Easy deploy
├── bash/
│   └── disk_space_monitor.sh            - Cron job alert
└── nodejs/
    └── basic_alert.js                   - Node.js example
```

---

## 🎯 Next Steps

1. **Choose your scenario** from the list above
2. **Copy example file** to your project
3. **Configure** (API endpoint, thresholds, etc.)
4. **Test** - Send test alert
5. **Deploy** - Run as service/cron/Docker
6. **Monitor** - Check logs, test auto-resolve

---

## 💡 Tips

### Performance
- Use appropriate check intervals (60s for most cases)
- Don't check too frequently (causes unnecessary load)

### Reliability
- Add health checks to monitoring agents
- Log to files for debugging
- Use systemd for auto-restart

### User Experience
- Use descriptive alert titles
- Include relevant metadata
- Test TTS messages (they'll be spoken!)

---

**Ready to get started?** Pick a scenario and copy the example! 🚀

