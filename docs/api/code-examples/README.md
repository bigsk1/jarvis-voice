# Jarvis API Integration Examples

Code examples for integrating external services with Jarvis Proactive Assistant API.

---

## Overview

Send alerts to Jarvis from any application or service using webhooks.

**Jarvis API Endpoint**: `http://localhost:8880/api/alerts`

**Required Fields**:
- `title`: Alert title
- `source`: Source system name

**Optional Fields** (for full features):
- `description`: Details
- `severity`: `low`, `medium`, `high`, `critical`
- `auto_resolve_url`: URL for auto-healing
- `auto_resolve_check_interval`: Check interval (seconds)
- `metadata`: Additional data (JSON)
- `related_intel_file`: Link to intel file

---

## Language Examples

- **[Python](python/)** - Flask, FastAPI, standalone scripts
- **[Node.js](nodejs/)** - Express, standalone scripts
- **[Bash](bash/)** - Cron jobs, system monitoring
- **[Docker](docker/)** - Containerized monitoring agents

---

## Use Cases

1. **Remote Server Monitoring** - Monitor Proxmox, VMs, containers
2. **Application Health** - Send alerts from your apps
3. **System Events** - Disk space, CPU, memory alerts
4. **Service Status** - Docker containers, systemd services
5. **Custom Integrations** - Any webhook-compatible service

---

## Quick Start

### Python Example

```python
import requests

def send_jarvis_alert(title, description, severity="medium"):
    response = requests.post(
        "http://localhost:8880/api/alerts",
        json={
            "title": title,
            "description": description,
            "severity": severity,
            "source": "my-app"
        }
    )
    return response.json()

# Usage
send_jarvis_alert("Server Down", "example.com not responding", "high")
```

### Node.js Example

```javascript
const axios = require('axios');

async function sendJarvisAlert(title, description, severity = 'medium') {
    const response = await axios.post('http://localhost:8880/api/alerts', {
        title,
        description,
        severity,
        source: 'my-app'
    });
    return response.data;
}

// Usage
sendJarvisAlert('Server Down', 'example.com not responding', 'high');
```

### Bash Example

```bash
#!/bin/bash
curl -X POST http://localhost:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d "{
    \"title\": \"Server Down\",
    \"description\": \"example.com not responding\",
    \"severity\": \"high\",
    \"source\": \"monitoring-script\"
  }"
```

---

## Remote Monitoring Setup

See **[Remote Monitoring Guide](../REMOTE_MONITORING.md)** for:
- Monitoring agents for remote servers
- Docker container monitoring
- Proxmox VM monitoring
- Security options (Tailscale, WireGuard, Cloudflare Tunnels)

---

## Integration Patterns

### Pattern 1: Direct Integration (Same Network)

```
Your App (192.168.1.100) → Jarvis API (192.168.1.50:8880)
```

Simple, no security concerns on local network.

### Pattern 2: Remote Agent (Internet)

```
Remote Server → Monitoring Agent → Secure Tunnel → Jarvis API
                                        ↓
                                  (Tailscale/WireGuard)
```

Agent runs on remote server, sends alerts through secure tunnel.

### Pattern 3: Push from External Service

```
Uptime Kuma (cloud) → Cloudflare Tunnel → Jarvis API
```

External service pushes webhooks through secure tunnel.

---

## Next Steps

1. Choose your language → See language-specific examples
2. Decide on deployment → See Remote Monitoring Guide
3. Secure your setup → See Security Options
4. Test integration → Use test scripts provided

---

## Support

- **Full API Docs**: [API_QUICK_START.md](../API_QUICK_START.md)
- **Remote Monitoring**: [REMOTE_MONITORING.md](../REMOTE_MONITORING.md)
- **Security**: [SECURITY_OPTIONS.md](../SECURITY_OPTIONS.md)
