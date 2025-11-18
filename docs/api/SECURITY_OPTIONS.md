# Security Options for Remote Access

## Overview

How to securely expose Jarvis API for remote monitoring without compromising security.

---

## ⭐ Recommended: Tailscale (Private Mesh Network)

**Best for**: Most users, especially for personal/home use

### Why Tailscale?

- ✅ **Zero trust network** - Not exposed to internet
- ✅ **End-to-end encrypted** - All traffic encrypted
- ✅ **Works behind NAT** - No port forwarding needed
- ✅ **Free for personal use** - Up to 100 devices
- ✅ **Zero configuration** - Just install and connect
- ✅ **Cross-platform** - Linux, Windows, Mac, mobile

### How It Works

```
Remote Server (Tailscale IP: 100.x.x.x)
         ↓
    [Encrypted Tunnel]
         ↓
Jarvis Server (Tailscale IP: 100.y.y.y)
```

**Your Jarvis API is NOT exposed to the internet** - only to devices on your Tailnet.

### Setup

**1. Install on Jarvis server:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4  # Note this IP (e.g., 100.101.102.103)
```

**2. Install on remote server:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**3. Configure monitoring agent:**
```yaml
# Use Tailscale IP in docker-compose.yml
JARVIS_API: "http://100.101.102.103:8880/api/alerts"
```

**That's it!** Your remote server can now reach Jarvis securely.

### Security Level
⭐⭐⭐⭐⭐ **Perfect for personal use**

---

## 🔒 Option 2: WireGuard VPN (Self-Hosted)

**Best for**: Advanced users who want full control

### Why WireGuard?

- ✅ **Self-hosted** - No third-party service
- ✅ **Fast** - Minimal overhead
- ✅ **Secure** - Modern cryptography
- ✅ **Full control** - You own the infrastructure

### How It Works

```
Remote Server (VPN IP: 10.0.0.2)
         ↓
    [WireGuard Tunnel]
         ↓
Jarvis Server (VPN IP: 10.0.0.1)
```

### Setup (Basic)

**On Jarvis server (VPN server):**
```bash
# Install WireGuard
sudo apt install wireguard

# Generate keys
wg genkey | tee privatekey | wg pubkey > publickey

# Configure /etc/wireguard/wg0.conf
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = <SERVER_PRIVATE_KEY>

[Peer]
PublicKey = <CLIENT_PUBLIC_KEY>
AllowedIPs = 10.0.0.2/32

# Start WireGuard
sudo wg-quick up wg0
sudo systemctl enable wg-quick@wg0
```

**On remote server (VPN client):**
```bash
# Similar setup with client config
# Point to server's public IP:51820
```

### Security Level
⭐⭐⭐⭐⭐ **Perfect, self-hosted**

---

## 🌐 Option 3: Cloudflare Tunnel (Zero Trust)

**Best for**: Exposing specific endpoints securely

### Why Cloudflare Tunnel?

- ✅ **No port forwarding** - Outbound connection only
- ✅ **DDoS protection** - Cloudflare's network
- ✅ **Access control** - Can add authentication
- ✅ **Free tier** - Available

### How It Works

```
Remote Server
    ↓
[Internet]
    ↓
Cloudflare Network (DDoS protection, WAF)
    ↓
Cloudflare Tunnel → Jarvis API (/api/* only)
```

### Setup

**1. Install cloudflared:**
```bash
# On Jarvis server
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
```

**2. Login and create tunnel:**
```bash
cloudflared tunnel login
cloudflared tunnel create jarvis-api
```

**3. Configure tunnel (expose only /api/*):**
```yaml
# ~/.cloudflared/config.yml
tunnel: <TUNNEL_ID>
credentials-file: /path/to/credentials.json

ingress:
  # Only expose API endpoints
  - hostname: jarvis-api.yourdomain.com
    path: /api/*
    service: http://localhost:8880
  
  # Block everything else
  - service: http_status:404
```

**4. Run tunnel:**
```bash
cloudflared tunnel run jarvis-api
```

**5. Update monitoring agent:**
```yaml
JARVIS_API: "https://jarvis-api.yourdomain.com/api/alerts"
```

### Security Enhancements

Add Cloudflare Access for authentication:
```bash
# Require email authentication
# Or use service tokens for automated access
```

### Security Level
⭐⭐⭐⭐ **Good, but traffic goes through Cloudflare**

---

## 🚫 Option 4: Direct Port Forward (NOT RECOMMENDED)

**Why NOT recommended:**
- ❌ Exposed to entire internet
- ❌ No encryption (unless you add HTTPS)
- ❌ Vulnerable to attacks
- ❌ Need strong authentication

**If you MUST do this:**

### Minimal Security Setup

**1. Add API key authentication:**
```python
# In api/middleware/auth.py
from fastapi import Header, HTTPException

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != os.getenv("JARVIS_API_KEY"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_api_key
```

**2. Use HTTPS (with Let's Encrypt):**
```bash
# Install certbot
sudo apt install certbot

# Get certificate
sudo certbot certonly --standalone -d jarvis.yourdomain.com
```

**3. Configure Nginx reverse proxy:**
```nginx
server {
    listen 443 ssl;
    server_name jarvis.yourdomain.com;
    
    ssl_certificate /etc/letsencrypt/live/jarvis.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jarvis.yourdomain.com/privkey.pem;
    
    # Only allow /api/* endpoints
    location /api/ {
        proxy_pass http://localhost:8880;
        
        # Rate limiting
        limit_req zone=api_limit burst=10;
        
        # IP whitelist (optional)
        allow 1.2.3.4;  # Your remote server IP
        deny all;
    }
    
    # Block everything else
    location / {
        return 404;
    }
}
```

**4. Add rate limiting:**
```nginx
# In nginx.conf
http {
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/m;
}
```

### Security Level
⭐⭐ **Risky, use only if no other option**

---

## 🔐 Comparison Table

| Option | Ease of Setup | Security | Cost | Speed | Maintenance |
|--------|--------------|----------|------|-------|-------------|
| **Tailscale** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Free | Fast | Zero |
| **WireGuard** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Free | Fastest | Low |
| **Cloudflare Tunnel** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Free tier | Good | Low |
| **Port Forward** | ⭐⭐ | ⭐⭐ | Free | Good | High |

---

## 📋 Recommendations by Use Case

### Home Lab / Personal Use
→ **Tailscale** (easiest, most secure)

### Multiple Remote Servers
→ **Tailscale** or **WireGuard** (scales well)

### Cloud-Based Monitoring
→ **Cloudflare Tunnel** (good for cloud VMs)

### Temporary/Testing
→ **Reverse SSH Tunnel** (quick and dirty)

### Production/Enterprise
→ **WireGuard** + **Authentication** + **Monitoring**

---

## 🛡️ Additional Security Measures

### 1. API Key Authentication

Add to Jarvis API:

```python
# config/cloud.env
JARVIS_API_KEY="your-secure-random-key-here"

# api/middleware/auth.py
from fastapi import Security, HTTPException
from fastapi.security.api_key import APIKeyHeader

API_KEY = os.getenv("JARVIS_API_KEY")
api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key
```

Use in monitoring agent:
```python
headers = {"X-API-Key": "your-secure-random-key-here"}
requests.post(JARVIS_API, json=payload, headers=headers)
```

### 2. IP Whitelist

Restrict to known IPs:

```python
# api/middleware/ip_filter.py
from fastapi import Request, HTTPException

ALLOWED_IPS = ["192.168.1.0/24", "100.0.0.0/8"]  # Tailscale range

async def ip_filter(request: Request):
    client_ip = request.client.host
    if not any(ip_in_network(client_ip, network) for network in ALLOWED_IPS):
        raise HTTPException(status_code=403, detail="IP not allowed")
```

### 3. Rate Limiting

Prevent abuse:

```python
# api/middleware/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/alerts")
@limiter.limit("10/minute")  # Max 10 alerts per minute
async def create_alert(...):
    ...
```

### 4. Request Size Limits

```python
# api/server.py
app = FastAPI(
    ...
    # Limit request body size
    openapi_url="/api/openapi.json"  # Hide docs in production
)

# Or in Nginx:
client_max_body_size 1M;
```

---

## 🎯 Final Recommendation

**For your Proxmox setup monitoring ComfyUI/Kokoro-TTS:**

**Use Tailscale!**

**Why:**
1. **5-minute setup** - Install on both servers, done
2. **Zero config** - No port forwarding, no firewall rules
3. **Maximum security** - Private mesh network
4. **Free** - No cost
5. **Works everywhere** - Home, cloud, mobile

**Alternative:** If you want complete control, use **WireGuard**.

**Avoid:** Direct port forwarding unless you add multiple security layers.

---

## 🧪 Testing Security

### Test Tailscale Connection

```bash
# On remote server
ping [JARVIS_TAILSCALE_IP]

# Test API
curl http://[JARVIS_TAILSCALE_IP]:8880/api/health

# Send test alert
curl -X POST http://[JARVIS_TAILSCALE_IP]:8880/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "source": "test", "severity": "medium"}'
```

### Verify Not Exposed to Internet

```bash
# From internet (should FAIL)
curl http://[YOUR_PUBLIC_IP]:8880/api/health
# Should timeout or be refused

# From Tailscale (should WORK)
curl http://[TAILSCALE_IP]:8880/api/health
# Should return {"status": "ok"}
```

---

## 📚 Resources

- **Tailscale Docs**: https://tailscale.com/kb/
- **WireGuard Setup**: https://www.wireguard.com/quickstart/
- **Cloudflare Tunnels**: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
- **FastAPI Security**: https://fastapi.tiangolo.com/tutorial/security/

---

## Summary

**For Personal/Home Use:**
→ Tailscale (5 min setup, maximum security)

**Don't expose Jarvis API directly to internet** without:
1. HTTPS
2. Authentication
3. Rate limiting
4. IP whitelist
5. WAF/firewall

**Best practice:** Use a private network (Tailscale/WireGuard) and skip all the complexity! 🎯

