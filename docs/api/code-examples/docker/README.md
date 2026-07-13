# Jarvis Monitoring Agent (Docker)

Universal monitoring agent that runs in Docker and sends alerts to Jarvis.

---

## Features

- ✅ Monitor Docker containers (running/stopped)
- ✅ Monitor HTTP/HTTPS endpoints
- ✅ Auto-resolve alerts when services come back
- ✅ Configurable via environment variables
- ✅ Graceful shutdown
- ✅ Health check included
- ✅ Lightweight (~50MB image)

---

## Quick Start

### 1. Install Tailscale (Recommended for Remote Access)

**On Jarvis server:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4  # Note this IP
```

**On remote server:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

### 2. Deploy Monitoring Agent

```bash
# Clone or copy monitoring agent files
mkdir ~/jarvis-monitor
cd ~/jarvis-monitor

# Copy files
wget https://raw.githubusercontent.com/YOUR_REPO/jarvis-voice/main/docs/api/code-examples/docker/Dockerfile
wget https://raw.githubusercontent.com/YOUR_REPO/jarvis-voice/main/docs/api/code-examples/docker/monitor.py
wget https://raw.githubusercontent.com/YOUR_REPO/jarvis-voice/main/docs/api/code-examples/docker/docker-compose.yml

# Or if you have the repo:
cp /path/to/jarvis-voice/docs/api/code-examples/docker/* .
```

### 3. Configure

Edit `docker-compose.yml`:

```yaml
environment:
  # Update with YOUR Jarvis server's Tailscale IP
  JARVIS_API: "http://100.101.102.103:8880/api/alerts"

  # Containers to monitor (comma-separated)
  MONITOR_CONTAINERS: "kokoro-tts,comfyui,ollama"

  # URLs to monitor (comma-separated)
  MONITOR_URLS: "http://localhost:8188/health,http://localhost:11434/health"

  # Source name (shows in Jarvis alerts)
  SOURCE_NAME: "proxmox-gpu-vm"
```

### 4. Start

```bash
docker compose up -d
```

### 5. Check Logs

```bash
docker compose logs -f
```

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
| `MONITOR_CONTAINERS` | `""` | Container names to monitor (comma-separated) |
| `MONITOR_URLS` | `""` | URLs to monitor (comma-separated) |
| `SOURCE_NAME` | hostname | Source name for alerts |
| `AUTO_RESOLVE_INTERVAL` | `60` | Auto-resolve check interval (seconds) |

### Example: Monitor Multiple Containers

```yaml
MONITOR_CONTAINERS: "nginx,redis,postgres,app,worker"
```

### Example: Monitor Multiple URLs

```yaml
MONITOR_URLS: "http://localhost:8000/health,http://localhost:3000/api/health,http://192.168.1.100:9090"
```

---

## Logs

View logs in real-time:
```bash
docker compose logs -f
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
Monitoring URLs: http://localhost:8188/health, http://localhost:11434/health
============================================================

✅ Docker client initialized

[10:31:00] Status: URL(localhost:8188):✓ | URL(localhost:11434):✓ | kokoro-tts:✓ | comfyui:✓ | ollama:✓
[10:32:00] ❌ CONTAINER STOPPED: kokoro-tts (status: exited)
           ✅ Alert sent (ID: 42)
```

---

## Management

### Start
```bash
docker compose up -d
```

### Stop
```bash
docker compose down
```

### Restart
```bash
docker compose restart
```

### Update
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### View Status
```bash
docker compose ps
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
3. Verify JARVIS_API in docker-compose.yml is correct

### "Docker not available"

**Cause**: Can't access Docker socket

**Fix**:
1. Check Docker socket is mounted: `docker compose config | grep docker.sock`
2. Check permissions: `ls -la /var/run/docker.sock`
3. Add user to docker group: `sudo usermod -aG docker $USER`

### Container monitoring not working

**Cause**: Container names might be wrong

**Fix**:
1. List running containers: `docker ps --format "{{.Names}}"`
2. Update MONITOR_CONTAINERS with exact names
3. Restart agent: `docker compose restart`

---

## Advanced Usage

### Multiple Monitoring Agents

Deploy multiple agents for different services:

```bash
# Web services monitor
cd ~/jarvis-monitor-web
# Configure for web containers
docker compose up -d

# AI services monitor
cd ~/jarvis-monitor-ai
# Configure for AI containers
docker compose up -d
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

**Free!** Monitoring agent only uses:
- CPU: <1%
- RAM: ~30MB
- Network: Minimal (only when sending alerts)

**Jarvis TTS costs when alerts trigger**: ~$0.015/1K characters

---

## See Also

- **[Remote Monitoring Guide](../../REMOTE_MONITORING.md)** - Complete setup guide
- **[Security Options](../../SECURITY_OPTIONS.md)** - Secure remote access
- **[Python Examples](../python/)** - Standalone Python scripts
- **[Bash Examples](../bash/)** - Shell scripts for monitoring

