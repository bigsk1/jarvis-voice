# Remote Monitoring Setup Guide

## Overview

Monitor remote servers, VMs, and Docker containers from anywhere and send alerts to your local Jarvis instance.

---

## Your Use Case: Proxmox GPU VM Monitoring

**Scenario**: You have:
- Ubuntu 24.04 server running Proxmox
- VM with GPU passthrough running ComfyUI
- Docker container running Kokoro-TTS
- Want alerts if server/VM/containers go offline

**Goal**: Send webhooks from remote server to local Jarvis API

---

## Architecture Options

### Option 1: Tailscale (Recommended ⭐)

**Best for**: Private, secure, zero-config mesh network

```
Remote Server (Tailscale IP: 100.x.x.x)
    ↓
Secure Tunnel (Tailscale)
    ↓
Jarvis Server (Tailscale IP: 100.y.y.y:8880)
```

**Pros:**
- ✅ Private mesh network (not exposed to internet)
- ✅ End-to-end encrypted
- ✅ Works behind NAT/firewalls
- ✅ Free for personal use
- ✅ Zero config (no port forwarding)

**Setup:**
1. Install Tailscale on both servers
2. Join same tailnet
3. Use Tailscale IPs: `http://100.y.y.y:8880/api/alerts`

**Security**: ⭐⭐⭐⭐⭐ (Private network, not exposed)

---

### Option 2: WireGuard VPN

**Best for**: Full control, self-hosted VPN

```
Remote Server (VPN IP: 10.0.0.2)
    ↓
WireGuard Tunnel
    ↓
Jarvis Server (VPN IP: 10.0.0.1:8880)
```

**Pros:**
- ✅ Self-hosted (no third party)
- ✅ Fast and secure
- ✅ Full control

**Cons:**
- ⚠️ More setup required
- ⚠️ Need static IP or DDNS

**Security**: ⭐⭐⭐⭐⭐ (Private VPN)

---

### Option 3: Cloudflare Tunnel (Zero Trust)

**Best for**: Expose specific endpoints securely

```
Remote Server
    ↓
Internet
    ↓
Cloudflare Tunnel → Jarvis API (/api/alerts only)
```

**Pros:**
- ✅ No port forwarding
- ✅ Cloudflare protection
- ✅ Can expose only /api/* endpoints
- ✅ Free tier available

**Cons:**
- ⚠️ Traffic goes through Cloudflare
- ⚠️ Requires domain name

**Security**: ⭐⭐⭐⭐ (Good, but third party)

---

### Option 4: Reverse SSH Tunnel

**Best for**: Quick temporary setup

```
Remote Server → SSH Tunnel → Jarvis Server
```

**Pros:**
- ✅ Quick setup
- ✅ Uses existing SSH

**Cons:**
- ⚠️ Requires SSH access
- ⚠️ Can be unstable
- ⚠️ Not designed for 24/7

**Security**: ⭐⭐⭐ (OK for temporary)

---

## Recommended: Tailscale Setup

### Step 1: Install Tailscale

**On Jarvis server:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**On remote Proxmox server:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

### Step 2: Get Tailscale IPs

```bash
# On Jarvis server
tailscale ip -4
# Example output: 100.101.102.103

# On remote server
tailscale ip -4
# Example output: 100.101.102.104
```

### Step 3: Update Monitoring Agent

Use Tailscale IP for Jarvis API:

```python
# On remote server
JARVIS_API = "http://100.101.102.103:8880/api/alerts"
```

**That's it!** Your remote server can now reach Jarvis securely.

---

## Monitoring Agent (Docker)

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install requests docker

# Copy monitoring script
COPY monitor.py /app/

# Run monitor
CMD ["python", "/app/monitor.py"]
```

### monitor.py

```python
#!/usr/bin/env python3
"""
Universal Monitoring Agent
Monitors services and Docker containers, sends alerts to Jarvis
"""
import os
import requests
import docker
import time
import sys

# Configuration from environment variables
JARVIS_API = os.getenv("JARVIS_API", "http://localhost:8880/api/alerts")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
MONITOR_CONTAINERS = os.getenv("MONITOR_CONTAINERS", "").split(",")
MONITOR_URLS = os.getenv("MONITOR_URLS", "").split(",")
SOURCE_NAME = os.getenv("SOURCE_NAME", os.uname().nodename)

def send_alert(title, description, severity, auto_resolve_url=None):
    """Send alert to Jarvis."""
    payload = {
        "title": title,
        "description": description,
        "severity": severity,
        "source": SOURCE_NAME,
    }

    if auto_resolve_url:
        payload["auto_resolve_url"] = auto_resolve_url
        payload["auto_resolve_check_interval"] = 300

    try:
        response = requests.post(JARVIS_API, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Failed to send alert: {e}", file=sys.stderr)
        return None

def check_url(url):
    """Check if URL is responding."""
    try:
        response = requests.get(url, timeout=10)
        return response.status_code == 200
    except:
        return False

def check_container(client, name):
    """Check if Docker container is running."""
    try:
        container = client.containers.get(name)
        return container.status == "running"
    except:
        return False

def main():
    """Main monitoring loop."""
    print(f"🔍 Monitoring Agent Started")
    print(f"   Jarvis API: {JARVIS_API}")
    print(f"   Source: {SOURCE_NAME}")
    print(f"   Interval: {CHECK_INTERVAL}s")
    print(f"   Containers: {MONITOR_CONTAINERS}")
    print(f"   URLs: {MONITOR_URLS}")
    print()

    # Initialize Docker client
    docker_client = None
    if MONITOR_CONTAINERS and MONITOR_CONTAINERS[0]:
        try:
            docker_client = docker.from_env()
        except:
            print("⚠️  Docker not available")

    last_status = {}

    while True:
        # Check URLs
        for url in MONITOR_URLS:
            if not url:
                continue

            is_up = check_url(url)
            prev = last_status.get(url)

            if prev and not is_up:
                print(f"❌ {url} is DOWN")
                send_alert(
                    f"Service Down: {url}",
                    f"URL {url} is not responding",
                    "high",
                    auto_resolve_url=url
                )
            elif prev == False and is_up:
                print(f"✅ {url} is back UP")

            last_status[url] = is_up

        # Check Docker containers
        if docker_client:
            for container_name in MONITOR_CONTAINERS:
                if not container_name:
                    continue

                is_running = check_container(docker_client, container_name)
                prev = last_status.get(container_name)

                if prev and not is_running:
                    print(f"❌ Container {container_name} stopped")
                    send_alert(
                        f"Container Stopped: {container_name}",
                        f"Docker container '{container_name}' is not running",
                        "high"
                    )
                elif prev == False and is_running:
                    print(f"✅ Container {container_name} started")

                last_status[container_name] = is_running

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n✋ Monitoring stopped")
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  jarvis-monitor:
    build: .
    restart: unless-stopped
    environment:
      # Jarvis API endpoint (use Tailscale IP)
      JARVIS_API: "http://100.101.102.103:8880/api/alerts"

      # Check interval (seconds)
      CHECK_INTERVAL: "60"

      # Docker containers to monitor (comma-separated)
      MONITOR_CONTAINERS: "kokoro-tts,comfyui,ollama"

      # URLs to monitor (comma-separated)
      MONITOR_URLS: "http://localhost:8188/health,http://localhost:11434/health"

      # Source name for alerts
      SOURCE_NAME: "proxmox-gpu-vm"

    volumes:
      # Mount Docker socket to monitor containers
      - /var/run/docker.sock:/var/run/docker.sock:ro

    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge
```

### Deploy on Remote Server

```bash
# 1. Create directory
mkdir -p ~/jarvis-monitor
cd ~/jarvis-monitor

# 2. Copy files (Dockerfile, monitor.py, docker-compose.yml)

# 3. Update JARVIS_API in docker-compose.yml with your Tailscale IP

# 4. Start monitor
docker compose up -d

# 5. View logs
docker compose logs -f
```

---

## Complete Example: Your Proxmox Setup

### Architecture

```
Proxmox Server (100.101.102.104)
    ├── VM: GPU-VM (ComfyUI)
    │   ├── Docker: kokoro-tts
    │   ├── Docker: comfyui
    │   └── Monitoring Agent (Docker)
    │        ↓
    │   Tailscale Tunnel
    │        ↓
    └── Jarvis Server (100.101.102.103:8880)
         └── Jarvis API receives alerts
```

### Setup Steps

**1. Install Tailscale on both servers**

**2. On Proxmox GPU VM, create monitoring agent:**

```bash
mkdir ~/jarvis-monitor
cd ~/jarvis-monitor

# Copy monitor files from docs/api/code-examples/docker/
cp -r docs/api/code-examples/docker/* .

# Edit docker-compose.yml
nano docker-compose.yml
# Update JARVIS_API with Jarvis server's Tailscale IP
```

**3. Start monitoring:**

```bash
docker compose up -d
```

**4. Test:**

```bash
# Stop a container
docker stop kokoro-tts

# Check Jarvis logs
# On Jarvis server:
curl http://localhost:8880/api/alerts
```

**5. Jarvis speaks:**
> "Boss, urgent alert! Container Stopped: kokoro-tts"

---

## Security Best Practices

### ✅ DO:
- Use Tailscale or WireGuard (private networks)
- Monitor only on private IPs
- Use API keys if exposing publicly (see SECURITY_OPTIONS.md)
- Limit exposed endpoints to `/api/*` only
- Use HTTPS if exposing to internet

### ❌ DON'T:
- Expose Jarvis API directly to internet without protection
- Use port forwarding without firewall rules
- Send sensitive data in webhook payloads
- Use unencrypted connections over internet

---

## Testing Your Setup

### 1. Test from Remote Server

```bash
# On remote server
curl -X POST http://[TAILSCALE_IP]:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test from Remote",
    "description": "Testing connection",
    "severity": "medium",
    "source": "test"
  }'
```

### 2. Check Jarvis Received It

```bash
# On Jarvis server
curl http://localhost:8880/api/alerts
```

### 3. Voice Query

> "Hey Jarvis, list pending alerts"

---

## Troubleshooting

### Can't reach Jarvis API from remote

1. **Check Tailscale status:**
   ```bash
   tailscale status
   ```

2. **Test connectivity:**
   ```bash
   ping [JARVIS_TAILSCALE_IP]
   ```

3. **Check Jarvis API is running:**
   ```bash
   curl http://localhost:8880/api/health
   ```

4. **Check firewall (if applicable):**
   ```bash
   sudo ufw status
   # Allow Tailscale interface:
   sudo ufw allow in on tailscale0
   ```

---

## Next Steps

1. **Choose security option** → Tailscale (recommended)
2. **Deploy monitoring agent** → Docker compose
3. **Test alerts** → Stop a service, check if Jarvis alerts
4. **Expand monitoring** → Add more services/containers
5. **Create intel files** → Document your infrastructure

See also:
- **[Code Examples](code-examples/)** - More integration examples
- **[SECURITY_OPTIONS.md](SECURITY_OPTIONS.md)** - Detailed security options
- **[Docker Monitoring Agent](code-examples/docker/)** - Complete agent setup

