# Jarvis Authentication Overview

Comprehensive guide to authentication across all Jarvis components.

**Last Updated:** February 2026

## Auth Surface Summary

| Component | Auth Type | Status | Notes |
|-----------|-----------|--------|-------|
| **Web UIs** (jarvis-web, canvas, memory, intel) | JWT (password) | ✅ Enabled | Single sign-on, see below |
| **FastAPI** (`/api/*`) | API Key (Bearer) | ✅ Enabled | See [SECURITY_OPTIONS.md](../api/SECURITY_OPTIONS.md) |
| **Internal API calls** (Canvas → API, etc.) | API Key | ✅ Fixed 2026-02-04 | Uses same `JARVIS_API_KEY` |
| **UniFi webhook receiver** (inbound) | None | ⚠️ Local only | Port 5050, not exposed to internet |
| **UniFi webhook → Jarvis API** (outbound) | API Key | ✅ Enabled | `JARVIS_API_KEY` in service config |
| **MCP servers** | None | ⚠️ Local only | stdio transport, same machine |

## Related Documentation

- **API Security & Remote Access:** [docs/api/SECURITY_OPTIONS.md](../api/SECURITY_OPTIONS.md)
- **UniFi Webhook Service:** [services/unifi-protect-webhook/README.md](../../services/unifi-protect-webhook/README.md)

## Future Auth Considerations

- **UniFi Webhook Inbound:** Could add webhook secret/signature validation if exposed
- **MCP Remote Transport:** Would need auth if using HTTP/SSE transport instead of stdio

---

# WebUI Authentication

Optional password protection for all Jarvis web interfaces.

## Overview

When enabled, all web UIs require authentication:
- **jarvis-web** (port 5001) - Main chat interface
- **jarvis-canvas** (port 8890) - Artifact viewer
- **jarvis-intelligence** (port 5003) - Intelligence dashboard  
- **jarvis-memory** (port 5002) - Memory browser

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (localStorage)                    │
│                    jarvis_auth_token = "eyJ..."                 │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   ┌───────────┐        ┌───────────┐        ┌───────────┐
   │ jarvis-web│        │  canvas   │        │  memory   │
   │   :5001   │        │   :8890   │        │   :5002   │
   │           │        │           │        │           │
   │ Validates │        │ Validates │        │ Validates │
   │ same JWT  │        │ same JWT  │        │ same JWT  │
   └───────────┘        └───────────┘        └───────────┘
```

- **Single Sign-On**: Login once on any UI, access all UIs
- **JWT Tokens**: Stored in browser localStorage (shared across ports)
- **30-day expiry**: Configurable via `WEBUI_TOKEN_EXPIRY_DAYS`
- **Stateless**: No server-side session storage required

## Configuration

Add to both `config/cloud.env` AND `config/local.env`:

```bash
# Required: Set a password to enable auth
WEBUI_PASSWORD="your-secure-password"

# Optional: Token expiry in days (default: 30)
WEBUI_TOKEN_EXPIRY_DAYS=30

# Optional: Custom JWT signing secret (auto-generated if not set)
# WEBUI_SECRET="your-secret-here"
```

**Important:** Set the same password in BOTH env files since the WebUI can switch modes.

## Enabling/Disabling

| WEBUI_PASSWORD | Behavior |
|----------------|----------|
| Not set or empty | Auth disabled - open access |
| Set to any value | Auth enabled - login required |

## Login Flow

1. User visits any protected page (e.g., `http://host:5001/`)
2. Server checks for valid JWT in:
   - `Authorization: Bearer <token>` header
   - `jarvis_auth` cookie
   - `?auth_token=` query parameter
3. If no valid token → redirect to `/login?redirect=/original-path`
4. User enters password → server returns JWT
5. JWT stored in localStorage and as cookie
6. User redirected to original destination
7. Subsequent requests include JWT automatically

## API Endpoints

All UIs expose these auth endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/status` | GET | Check if auth is enabled |
| `/api/auth/login` | POST | Login with `{"password": "..."}` |
| `/api/auth/verify` | GET | Verify current token is valid |
| `/api/auth/logout` | POST | Logout (client clears token) |

### Example: Login via API

```bash
# Check if auth is enabled
curl http://localhost:5001/api/auth/status

# Login
curl -X POST http://localhost:5001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "your-password"}'

# Response: {"ok": true, "token": "eyJ...", "expires_in_days": 30}

# Use token for authenticated requests
curl http://localhost:5001/api/settings \
  -H "Authorization: Bearer eyJ..."
```

## Invalidating All Tokens

To force all users to re-login:

```bash
# Delete the signing secret (will be regenerated on restart)
rm data/.webui_secret

# Restart all web UIs
```

This invalidates ALL existing tokens immediately.

## Security Notes

1. **Private Network**: If running on a trusted private network, you may not need auth
2. **HTTPS**: For public exposure, use a reverse proxy with HTTPS
3. **Password Strength**: Use a strong password - it's the only barrier
4. **Token Storage**: JWTs are stored in localStorage (vulnerable to XSS)
5. **No Rate Limiting**: Currently no brute-force protection on login

## Auth Logs

Auth events are logged to `logs/auth/auth-YYYY-MM-DD.jsonl`:

```bash
# View today's auth log
cat logs/auth/auth-$(date +%Y-%m-%d).jsonl | jq .

# Find failed auth attempts
grep '"success":false' logs/auth/auth-*.jsonl
```

**Logged events:**
- `login_success` - Successful login
- `password_verify` (failed) - Invalid password attempt
- `token_verify` (failed) - Invalid/expired token
- `request_blocked` - Request blocked by middleware (if enabled)

## Troubleshooting

### "Invalid password" but password is correct

Check both env files have the same password:
```bash
grep WEBUI_PASSWORD config/cloud.env config/local.env
```

### Auth not working after password change

Clear browser storage:
- Open DevTools → Application → Local Storage → Clear `jarvis_auth_token`
- Or delete cookies for the site

### Force re-login for all sessions

```bash
rm data/.webui_secret
# Restart servers
```

## Architecture

```
lib/webui_auth.py          # Shared auth library (JWT, password verification)
    │
    ├── jarvis-web/
    │   ├── client/login.html      # Login page
    │   └── server/routes/auth.py  # Auth API routes
    │
    ├── jarvis-canvas/
    │   ├── client/login.html
    │   └── server/routes/auth.py
    │
    ├── jarvis-intelligence/
    │   ├── client/login.html
    │   └── server/routes/auth.py
    │
    └── jarvis-memory/
        ├── client/login.html
        └── server/routes/auth.py
```

All UIs share the same `lib/webui_auth.py` for consistent token handling.
