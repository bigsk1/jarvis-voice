<div align="center">
  <img src="https://imagedelivery.net/WfhVb8dSNAAvdXUdMfBuPQ/accb8e7c-4161-4e38-55ac-71b320c44300/public" alt="Jarvis Monitor Banner" width="100%">
  
  # Jarvis Monitoring Agent (Docker)
  
  Universal monitoring agent that runs in Docker and sends alerts to Jarvis.
</div>

---

## Features

- ✅ Monitor Docker containers (running/stopped)
- ✅ Monitor HTTP/HTTPS endpoints
- ✅ Auto-resolve alerts when services come back
- ✅ Configurable via environment variables
- ✅ Graceful shutdown
- ✅ Health check included
- ✅ Lightweight (~50MB image)
- ✅ Public Docker image - no build required!

---

## Quick Start (Docker Run - Recommended)

**The fastest way to get started - just pull and run!**

### One-liner (Quick Deploy)
```bash
docker pull bigsk1/jarvis-monitor:latest && \
docker run -d \
  --name jarvis-monitor \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e JARVIS_API="http://YOUR_JARVIS_IP:8880/api/alerts" \
  -e SOURCE_NAME="my-server" \
  -e MONITOR_CONTAINERS="container1,container2" \
  bigsk1/jarvis-monitor:latest && \
docker logs -f jarvis-monitor
```

Replace:
- `YOUR_DOCKERHUB_USERNAME` with the actual Docker Hub username
- `YOUR_JARVIS_IP` with your Jarvis server IP (Tailscale recommended)
- `my-server` with a descriptive name for this server
- `container1,container2` with containers to monitor (or leave empty)

---

### Step-by-step

### 1. Pull the image
```bash
docker pull bigsk1/jarvis-monitor:latest
```

### 2. Run with environment variables
```bash
docker run -d \
  --name jarvis-monitor \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e JARVIS_API="http://YOUR_JARVIS_IP:8880/api/alerts" \
  -e SOURCE_NAME="my-server" \
  -e MONITOR_CONTAINERS="nginx,redis,postgres" \
  -e MONITOR_URLS="" \
  -e CHECK_INTERVAL="60" \
  -e AUTO_RESOLVE_INTERVAL="60" \
  bigsk1/jarvis-monitor/jarvis-monitor:latest
```

### 3. Check logs
```bash
docker logs -f jarvis-monitor
```

### Example: Monitor Containers
```bash
docker run -d \
  --name jarvis-monitor \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e JARVIS_API="http://100.101.102.103:8880/api/alerts" \
  -e SOURCE_NAME="production-server" \
  -e MONITOR_CONTAINERS="webapp,database,cache" \
  bigsk1/jarvis-monitor:latest
```

### Example: Monitor URLs (with friendly names)
```bash
docker run -d \
  --name jarvis-monitor \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e JARVIS_API="http://100.101.102.103:8880/api/alerts" \
  -e SOURCE_NAME="web-services" \
  -e MONITOR_URLS="proxmox-main|http://192.168.1.100:8080/health,webapp|http://localhost:3000/api/status" \
  bigsk1/jarvis-monitor:latest
```

**Note**: Named URLs use the format `friendly-name|url`. TTS will say "proxmox-main is down" instead of the raw URL.

### Example: Monitor Both Containers and URLs
```bash
docker run -d \
  --name jarvis-monitor \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e JARVIS_API="http://100.101.102.103:8880/api/alerts" \
  -e SOURCE_NAME="ai-server" \
  -e MONITOR_CONTAINERS="ollama,comfyui,kokoro-tts" \
  -e MONITOR_URLS="ollama-api|http://localhost:11434/health,comfyui-web|http://localhost:8188/health" \
  bigsk1/jarvis-monitor:latest
```

---

## Alternative: Docker Compose (More Configuration Options)

If you prefer using docker-compose for easier management:

### 1. Download files
```bash
# Create directory
mkdir ~/jarvis-monitor && cd ~/jarvis-monitor

# Download docker-compose.yml and .env.example
wget https://raw.githubusercontent.com/bigsk1/jarvis-monitor/main/docker-compose.yml
wget https://raw.githubusercontent.com/bigsk1/jarvis-monitor/main/.env.example
```

### 2. Configure
```bash
# Create .env from example
cp .env.example .env

# Edit with your values
nano .env
```

### 3. Start
```bash
docker-compose up -d
```

### 4. Check logs
```bash
docker-compose logs -f
```

---

## Tailscale Setup (Recommended for Remote Access)

For secure remote monitoring, use Tailscale to connect your servers:

**On Jarvis server:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4  # Note this IP (e.g., 100.101.102.103)
```

**On remote server (where monitor runs):**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**Test connectivity:**
```bash
ping 100.101.102.103  # Your Jarvis Tailscale IP
curl http://100.101.102.103:8880/api/alerts
```

Then use the Tailscale IP in your `JARVIS_API` environment variable!

---

## Testing

### Test Alert

Stop a monitored container:
```bash
docker stop kokoro-tts
```

**Jarvis should speak:**
> "Boss, urgent alert! Container Stopped: kokoro-tts"

### Check Jarvis

```bash
# On Jarvis server
curl http://localhost:8880/api/alerts
```

Or via voice:
> "Hey Jarvis, list pending alerts"

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JARVIS_API` | `http://localhost:8880/api/alerts` | Jarvis API endpoint |
| `CHECK_INTERVAL` | `60` | Check interval (seconds) |
| `ALERT_TIMEOUT` | `30` | Timeout for Jarvis API calls (seconds) - increase if TTS is slow |
| `MONITOR_CONTAINERS` | `""` | Container names to monitor (comma-separated) |
| `MONITOR_URLS` | `""` | URLs to monitor - supports named URLs (see below) |
| `SOURCE_NAME` | hostname | Source name for alerts |
| `ALERT_ON_START` | `false` | Send alert when agent starts |

### Example: Monitor Multiple Containers

```yaml
MONITOR_CONTAINERS: "nginx,redis,postgres,app,worker"
```

### Example: Monitor Multiple URLs

**Simple format** (URL only):
```yaml
MONITOR_URLS: "http://localhost:8000/health,http://localhost:3000/api/health"
```

**Named format** (recommended - TTS will speak the friendly name):
```yaml
# Format: friendly-name|url
MONITOR_URLS: "proxmox-main|http://192.168.1.100:8080/health,web-server|http://192.168.1.100:9090"
```

With named URLs, Jarvis will say:
> "Boss, urgent alert! Service Down: proxmox-main"

Instead of:
> "Boss, urgent alert! Service Down: http://192.168.1.100:8080/health"

**Mix both formats**:
```yaml
MONITOR_URLS: "proxmox-main|http://192.168.1.100:8080/health,http://localhost:3000/api/health"
```

---

## Logs

View logs in real-time:
```bash
docker-compose logs -f
```

Example output:
```
============================================================
🔍 Jarvis Monitoring Agent
============================================================
Started: 2025-11-18 10:30:00
Jarvis API: http://100.101.102.103:8880/api/alerts
Source Name: proxmox-gpu-vm
Check Interval: 60s
Monitoring Containers: kokoro-tts, comfyui, ollama
Monitoring URLs: comfyui-web (http://localhost:8188/health), ollama-api (http://localhost:11434/health)
============================================================

✅ Docker client initialized

[10:31:00] Status: comfyui-web:✓ | ollama-api:✓ | kokoro-tts:✓ | comfyui:✓ | ollama:✓
[10:32:00] ❌ CONTAINER STOPPED: kokoro-tts (status: exited)
           ✅ Alert sent (ID: 42)
[10:33:00] ❌ URL DOWN: proxmox-main (http://192.168.1.100:8080/health)
           ✅ Alert sent (ID: 43)
```

---

## Management

### Using Docker Run

**Start**
```bash
docker start jarvis-monitor
```

**Stop**
```bash
docker stop jarvis-monitor
```

**Restart**
```bash
docker restart jarvis-monitor
```

**Update to latest image**
```bash
docker stop jarvis-monitor
docker rm jarvis-monitor
docker pull bigsk1/jarvis-monitor:latest
# Then run the docker run command again with your env vars
```

**View logs**
```bash
docker logs -f jarvis-monitor
```

**View status**
```bash
docker ps -a | grep jarvis-monitor
```

**Remove**
```bash
docker stop jarvis-monitor
docker rm jarvis-monitor
```

### Using Docker Compose

**Start**
```bash
docker-compose up -d
```

**Stop**
```bash
docker-compose down
```

**Restart**
```bash
docker-compose restart
```

**Update**
```bash
docker-compose pull
docker-compose up -d
```

**View logs**
```bash
docker-compose logs -f
```

**View status**
```bash
docker-compose ps
```

---

## Security

### ✅ Best Practices

1. **Use Tailscale/WireGuard** for remote access (not port forwarding)
2. **Mount Docker socket as read-only**: `:ro`
3. **Don't expose Jarvis API to internet** without protection
4. **Use environment variables** for configuration (not hardcoded)

### Docker Socket Access

The agent needs read access to Docker socket to monitor containers:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro  # :ro = read-only
```

**Security note**: This gives the container read access to Docker. The `:ro` flag prevents writes.

---

## Troubleshooting

### "Failed to send alert: Connection refused"

**Cause**: Can't reach Jarvis API

**Fix**:
1. Check Jarvis API is running: `curl http://localhost:8880/api/health` (on Jarvis server)
2. Check Tailscale connectivity: `ping [JARVIS_TAILSCALE_IP]`
3. Verify JARVIS_API environment variable is correct
4. Check logs: `docker logs jarvis-monitor`

### "Failed to send alert: Read timed out"

**Cause**: Jarvis API is slow to respond (usually during TTS playback)

**Fix**:
1. Increase timeout: `-e ALERT_TIMEOUT=60` (default is 30s)
2. This is normal when Jarvis is speaking alerts - the TTS can take time
3. The alert may still have been received - check Jarvis logs or ask "list pending alerts"

### "Docker not available"

**Cause**: Can't access Docker socket

**Fix**:
1. Check Docker socket is mounted: `docker inspect jarvis-monitor | grep docker.sock`
2. Check permissions: `ls -la /var/run/docker.sock`
3. Add user to docker group: `sudo usermod -aG docker $USER`
4. Make sure volume is mounted: `-v /var/run/docker.sock:/var/run/docker.sock:ro`

### Container monitoring not working

**Cause**: Container names might be wrong

**Fix**:
1. List running containers: `docker ps --format "{{.Names}}"`
2. Update MONITOR_CONTAINERS environment variable with exact names
3. Restart agent: `docker restart jarvis-monitor`
4. Check logs: `docker logs jarvis-monitor`

---

## Advanced Usage

### Multiple Monitoring Agents

Deploy multiple agents for different services:

```bash
# Web services monitor
cd ~/jarvis-monitor-web
# Configure for web containers
docker-compose up -d

# AI services monitor
cd ~/jarvis-monitor-ai
# Configure for AI containers
docker-compose up -d
```

Each sends alerts with different SOURCE_NAME.

### Custom Health Checks

Some apps don't have `/health` endpoints. Use any URL:

```yaml
MONITOR_URLS: "http://localhost:8000/,http://localhost:3000/api/status"
```

Agent checks for 2xx/3xx status codes.

---

## Cost

Monitoring agent only uses:
- CPU: <1%
- RAM: ~30MB
- Network: Minimal (only when sending alerts)



