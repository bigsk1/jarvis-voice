# Jarvis Webhook System - Modular Design

## Overview

Jarvis uses a **modular webhook registry** for triggering external services and n8n workflows. This system provides:

- 📝 **Named webhooks** - Reference by name instead of URL
- 🔐 **Multiple auth methods** - Bearer, Basic, API Key, JWT, custom headers
- ⚡ **Rate limiting** - Prevent duplicate/spam requests
- 🎯 **Two-tier tools** - High-level (`send_email`) and low-level (`send_webhook`)
- 🔄 **Bidirectional sync** - Works with n8n for complex automations

```
┌─────────────────────────────────────────────────────────────┐
│  "Hey Jarvis, send email to Andrew" OR "trigger slack"     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              WEBHOOK REGISTRY (Ghost Tools)                 │
│  ┌──────────────────┐        ┌──────────────────┐          │
│  │  send_email      │        │  send_webhook    │          │
│  │  (high-level)    │        │  (generic)       │          │
│  └──────────────────┘        └──────────────────┘          │
│           │                            │                    │
│           └────────────┬───────────────┘                    │
│                        ▼                                    │
│         config/webhook_registry.json                        │
│         config/contacts.json                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  n8n Workflows OR External APIs (Slack, Discord, etc.)     │
└─────────────────────────────────────────────────────────────┘
```

---

## Architecture

### Configuration Files

| File | Purpose | Git Status |
|------|---------|------------|
| `config/webhook_registry.json` | Active webhook definitions (URLs, auth, rate limits) | ❌ Gitignored (your data) |
| `config/webhook_registry.json.example` | Template with examples | ✅ Committed |
| `config/contacts.json` | Email contact list (name → email mapping) | ❌ Gitignored (your data) |
| `config/contacts.json.example` | Template with examples | ✅ Committed |

### Runtime Files (Auto-Generated)

| File | Purpose |
|------|---------|
| `data/.email_rate_limit` | Email rate limiting cache (timestamps) |
| `data/.webhook_rate_limit` | Webhook rate limiting cache (timestamps) |

Both are gitignored and auto-created on first use.

---

## Tools

### `send_email` - High-Level Email Tool

**Purpose:** User-friendly email tool with contact name resolution.

**Voice Commands:**
- "Send an email to Andrew about the meeting"
- "Email mom and say happy birthday"
- "Send email to john@example.com with subject Hello"

**Parameters:**
```json
{
  "to": "andrew",           // Contact name OR email address
  "subject": "Meeting",
  "body": "Let's meet at 3pm"
}
```

**What it does:**
1. Resolves contact name → email (from `contacts.json`)
2. Looks up `send_email` webhook URL (from `webhook_registry.json`)
3. Checks rate limit (10 seconds per recipient)
4. POSTs to n8n webhook
5. n8n sends email via SMTP with HTML template

---

### `send_webhook` - Generic Webhook Tool

**Purpose:** Low-level tool for ANY webhook (n8n, Slack, APIs, etc.)

**Voice Commands:**
- "Trigger the slack webhook with message hello"
- "Send webhook to home_assistant with action lights_on"
- "List available webhooks"

**Parameters:**
```json
{
  "webhook": "slack_notify",  // Named webhook from registry
  "data": {                   // JSON payload to send
    "channel": "#general",
    "message": "Hello from Jarvis"
  },
  "headers": {                // Optional custom headers
    "Authorization": "Bearer abc123"
  }
}
```

**OR use direct URL (backward compatible):**
```json
{
  "url": "https://hooks.slack.com/services/YOUR/WEBHOOK",
  "data": {"text": "Hello"}
}
```

---

## Webhook Registry Format

### `config/webhook_registry.json`

```json
{
  "_description": "Registry of named webhooks Jarvis can trigger",
  "_usage": "Use webhook name instead of URL in send_webhook tool",
  
  "webhooks": {
    "webhook_name": {
      "url": "http://192.168.70.226:5678/webhook/endpoint",
      "description": "What this webhook does (shown to LLM)",
      "required_fields": ["field1", "field2"],
      "rate_limit_seconds": 10,
      "enabled": true,
      "example": {
        "field1": "value1",
        "field2": "value2"
      }
    }
  }
}
```

### Field Descriptions

| Field | Required | Description |
|-------|----------|-------------|
| `url` | ✅ | Webhook endpoint URL |
| `description` | ✅ | Clear description for LLM tool selection |
| `required_fields` | ⚠️ | Array of required data fields (validated before sending) |
| `rate_limit_seconds` | ⚠️ | Min seconds between calls (default: 5) |
| `enabled` | ⚠️ | Set to `false` to disable (default: true) |
| `example` | ⚠️ | Example payload for documentation |

---

## Authentication Methods

### 1. No Auth (Simple Webhooks)

```json
{
  "test_echo": {
    "url": "http://192.168.70.226:5678/webhook/test-echo",
    "description": "Test webhook that echoes back",
    "required_fields": ["message"],
    "rate_limit_seconds": 5
  }
}
```

**Usage:**
```bash
./jarvis "trigger test_echo with message hello world"
```

---

### 2. Bearer Token Auth (Most Common)

```json
{
  "my_api": {
    "url": "https://api.example.com/webhook",
    "description": "Trigger API with bearer token",
    "required_fields": ["action"],
    "rate_limit_seconds": 10
  }
}
```

**Usage with auth header:**
```bash
# Voice (LLM will handle header)
./jarvis "trigger my_api webhook with action deploy and use bearer token abc123"

# Programmatic (explicit)
./orchestrator/orchestrator_v2.py cloud '{
  "webhook": "my_api",
  "data": {"action": "deploy"},
  "headers": {"Authorization": "Bearer abc123"}
}'
```

**Better approach - Store in n8n:**
Instead of passing tokens in voice commands, create an n8n workflow:
```
Webhook Trigger → HTTP Request with stored credentials → External API
```

---

### 3. API Key in Header

**Example: Discord, Slack, custom APIs**

```json
{
  "discord_webhook": {
    "url": "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN",
    "description": "Send Discord notification",
    "required_fields": ["content"],
    "rate_limit_seconds": 5,
    "example": {
      "content": "Hello from Jarvis!"
    }
  }
}
```

**Note:** Discord/Slack webhooks have token in URL (no extra header needed).

For APIs requiring header:
```json
{
  "my_service": {
    "url": "https://api.service.com/webhook",
    "description": "Service API (requires X-API-Key header)",
    "required_fields": ["message"],
    "auth_note": "Pass X-API-Key header via send_webhook tool"
  }
}
```

**Usage:**
```python
# In Python tool/script
result = send_webhook(
    webhook="my_service",
    data={"message": "hello"},
    headers={"X-API-Key": "your-key-here"}
)
```

---

### 4. Basic Auth

**For services using HTTP Basic Authentication:**

```json
{
  "basic_auth_api": {
    "url": "https://api.example.com/webhook",
    "description": "API with basic auth (username:password)",
    "required_fields": ["data"],
    "rate_limit_seconds": 10
  }
}
```

**Implementation:**

**Option A - Via n8n (Recommended):**
```
Jarvis → n8n Webhook → HTTP Request (with stored credentials) → External API
```

**Option B - Direct (base64 encode username:password):**
```python
import base64
credentials = base64.b64encode(b"username:password").decode()

send_webhook(
    webhook="basic_auth_api",
    data={"data": "payload"},
    headers={"Authorization": f"Basic {credentials}"}
)
```

---

### 5. JWT (JSON Web Token)

**For OAuth2/JWT-based APIs:**

```json
{
  "jwt_api": {
    "url": "https://api.example.com/webhook",
    "description": "API requiring JWT token",
    "required_fields": ["action"],
    "rate_limit_seconds": 10,
    "auth_note": "JWT token expires, use n8n for token refresh"
  }
}
```

**Best Practice - Use n8n for Token Management:**

```
┌──────────────────────────────────────────────────┐
│  n8n Workflow: Handle JWT Refresh                │
│  1. Webhook Trigger (from Jarvis)                │
│  2. Check if JWT expired                         │
│  3. If expired → Refresh (OAuth2 flow)           │
│  4. HTTP Request with valid JWT → External API   │
└──────────────────────────────────────────────────┘
```

This way Jarvis doesn't need to handle token refresh logic.

---

### 6. Custom Headers (Any Auth Scheme)

**For services with unique auth requirements:**

```json
{
  "custom_api": {
    "url": "https://api.custom.com/webhook",
    "description": "API with custom headers",
    "required_fields": ["payload"],
    "rate_limit_seconds": 5,
    "auth_note": "Requires X-Custom-Auth and X-Timestamp headers"
  }
}
```

**Usage:**
```python
import time

send_webhook(
    webhook="custom_api",
    data={"payload": "data"},
    headers={
        "X-Custom-Auth": "your-secret",
        "X-Timestamp": str(int(time.time())),
        "X-Signature": "computed-hmac-signature"
    }
)
```

---

## Real-World Examples

### Example 1: Email System (Active)

**Registry:**
```json
{
  "send_email": {
    "url": "http://192.168.70.226:5678/webhook/jarvis-email",
    "description": "Send email via n8n SMTP",
    "required_fields": ["to", "subject", "body"],
    "rate_limit_seconds": 10
  }
}
```

**n8n Workflow:**
```
Webhook → Send Email (SMTP) → Respond
```

**Voice Usage:**
```bash
./jarvis "send email to boss about the meeting at 3pm"
```

---

### Example 2: Google Calendar Sync (Active)

**Registry:**
```json
{
  "jarvis_reminder": {
    "url": "http://192.168.70.226:5678/webhook/jarvis-reminder",
    "description": "Sync reminder to Google Calendar",
    "required_fields": ["action", "reminder"],
    "rate_limit_seconds": 5
  }
}
```

**Used by:** `skills/create_reminder.py` (automatic sync)

**n8n Workflow:**
```
Webhook → Parse Reminder → Create Google Calendar Event → Respond
```

---

### Example 3: Slack Notifications (Template)

**Registry:**
```json
{
  "notify_slack": {
    "url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "description": "Send message to #general channel",
    "required_fields": ["text"],
    "rate_limit_seconds": 5,
    "example": {
      "text": "Alert: Server restarted"
    }
  }
}
```

**Voice Usage:**
```bash
./jarvis "notify slack that the deployment completed successfully"
```

**Direct API (no n8n needed):**
Slack webhooks are simple POST requests - no auth header needed, token in URL.

---

### Example 4: Home Assistant (Template)

**Registry:**
```json
{
  "home_assistant": {
    "url": "http://homeassistant.local:8123/api/webhook/jarvis_automation",
    "description": "Trigger Home Assistant automation",
    "required_fields": ["action"],
    "rate_limit_seconds": 2,
    "enabled": false,
    "example": {
      "action": "lights_on",
      "room": "living_room"
    }
  }
}
```

**Setup in Home Assistant:**
1. Create webhook automation in HA
2. Get webhook URL
3. Update registry
4. Set `enabled: true`

**Voice Usage:**
```bash
./jarvis "turn on the living room lights via home assistant"
```

---

### Example 5: GitHub Webhook (With Auth)

**Use n8n as Proxy:**

**Registry:**
```json
{
  "github_deploy": {
    "url": "http://192.168.70.226:5678/webhook/github-action",
    "description": "Trigger GitHub Actions workflow",
    "required_fields": ["repo", "workflow"],
    "rate_limit_seconds": 30
  }
}
```

**n8n Workflow:**
```
Webhook (from Jarvis)
  ↓
HTTP Request Node:
  - URL: https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches
  - Method: POST
  - Headers:
      Authorization: Bearer {{ $credentials.github.token }}
      Accept: application/vnd.github.v3+json
  - Body: {"ref": "main"}
  ↓
Respond to Jarvis
```

**Why n8n proxy?**
- Keeps GitHub token secure (not in Jarvis code)
- Handles token refresh if needed
- Can add retry logic, logging, etc.

---

## Adding New Webhooks

### Step 1: Choose Integration Method

**Option A: Direct API (Simple)**
- Use if: Public webhook URL, no complex auth, no token refresh
- Examples: Slack webhooks, Discord webhooks, simple APIs

**Option B: Via n8n (Recommended for Complex)**
- Use if: OAuth2, JWT, token refresh, or complex logic
- Examples: GitHub, Google APIs, services with expiring tokens

---

### Step 2: Add to Registry

Edit `config/webhook_registry.json`:

```json
{
  "webhooks": {
    "my_new_webhook": {
      "url": "http://192.168.70.226:5678/webhook/my-endpoint",
      "description": "Clear description for LLM - what it does, when to use it",
      "required_fields": ["field1", "field2"],
      "rate_limit_seconds": 10,
      "enabled": true,
      "example": {
        "field1": "example value",
        "field2": "example value"
      }
    }
  }
}
```

---

### Step 3: Create n8n Workflow (if needed)

**Basic Template:**
```
1. Webhook Trigger
   - Path: /webhook/my-endpoint
   - Method: POST

2. Function/Code Node (optional)
   - Transform data
   - Validate payload

3. HTTP Request / Action Node
   - Call external API
   - Or perform action

4. Respond to Webhook
   - Return success/error
```

**Activate the workflow!**

---

### Step 4: Test

```bash
# Direct test
./orchestrator/orchestrator_v2.py cloud "trigger my_new_webhook with field1 value1 and field2 value2"

# Or via voice
./jarvis "trigger my new webhook with test data"
```

---

## Ghost Tools (Always Available)

Both webhook tools are configured as **ghost tools** - they're ALWAYS available to the LLM without semantic search:

**Config:** `config/cloud.env` and `config/local.env`
```bash
GHOST_TOOLS="search_memory,recall,semantic_recall,remember,check_tool_logs,get_recent_conversations,get_time,send_email,send_webhook"
```

**Why?** Email and webhooks are common actions that should always be accessible, like memory tools.

---

## Rate Limiting

### How It Works

1. Each webhook has `rate_limit_seconds` (default: 5)
2. After calling, timestamp stored in `data/.webhook_rate_limit`
3. Next call checks: `current_time - last_call_time >= limit`
4. If rate limited, returns error with remaining wait time

### Rate Limit Cache Format

**`data/.webhook_rate_limit`:**
```json
{
  "webhook_name_hash": 1732547890.123,
  "another_webhook_hash": 1732547920.456
}
```

Uses MD5 hash (first 8 chars) of webhook name/URL as key.

### Per-Recipient Limiting (Email)

Email tool uses separate file: `data/.email_rate_limit`
```json
{
  "email_hash": 1732547890.123
}
```

Each recipient has independent rate limit (10 seconds default).

---

## Troubleshooting

### Webhook Not Found

**Error:** `Webhook 'my_webhook' not found`

**Fix:**
1. Check `config/webhook_registry.json` for typo
2. Ensure webhook exists in `"webhooks": {...}`
3. Check `"enabled": true` (or omit, defaults to true)

**List available:**
```bash
./orchestrator/orchestrator_v2.py cloud "list available webhooks"
```

---

### Webhook Disabled

**Error:** `Webhook 'my_webhook' is disabled`

**Fix:** Set `"enabled": true` in registry

---

### Missing Required Fields

**Error:** `Missing required fields: field1, field2`

**Fix:** Check `required_fields` in registry and provide all fields:
```bash
./jarvis "trigger webhook with field1 value1 and field2 value2"
```

---

### Rate Limited

**Error:** `Rate limited. Please wait 5 seconds`

**Fix:** Wait the specified time, or adjust `rate_limit_seconds` in registry

**Force clear rate limit:**
```bash
rm data/.webhook_rate_limit data/.email_rate_limit
```

---

### n8n Webhook Not Found (404)

**Error:** `404 The requested webhook "POST my-webhook" is not registered`

**Fix:**
1. Open n8n workflow
2. Check webhook path matches registry URL
3. **Ensure workflow is ACTIVE** (toggle top-right)
4. Production URL only works when workflow is active

---

### Contact Not Found (Email)

**Error:** `Contact 'john' not found. Available contacts: andrew, mom, boss`

**Fix:** Add contact to `config/contacts.json`:
```json
{
  "contacts": {
    "john": {
      "name": "John Smith",
      "email": "john@example.com"
    }
  }
}
```

---

### Auth Failures (401/403)

**Error:** `Webhook failed with status 401` or `403 Forbidden`

**Common causes:**
1. **Missing auth header** - Add via `headers` parameter
2. **Expired token** - Refresh token (use n8n for auto-refresh)
3. **Wrong credentials** - Verify API key/token
4. **CORS issues** - Use n8n as proxy

**Debug:**
```bash
# Check n8n execution logs for details
# Open: http://192.168.70.226:5678/executions
```

---

## Best Practices

### 1. Use n8n for Complex Auth
✅ **DO:** Create n8n workflow to handle OAuth2, JWT refresh, complex auth
❌ **DON'T:** Put credentials directly in Jarvis code or voice commands

### 2. Clear Descriptions
✅ **DO:** "Send message to #general Slack channel. Use for alerts and notifications."
❌ **DON'T:** "Slack webhook"

### 3. Appropriate Rate Limits
- **Emails:** 10+ seconds (avoid spam)
- **Notifications:** 5-10 seconds
- **Quick actions:** 2-5 seconds
- **Critical commands:** 30+ seconds (deployments, etc.)

### 4. Validate Required Fields
Always specify `required_fields` to catch errors early:
```json
"required_fields": ["recipient", "message", "priority"]
```

### 5. Keep Secrets Out of Git
- ✅ Webhook URLs in `webhook_registry.json` (gitignored)
- ✅ API tokens in n8n credentials (secure storage)
- ❌ Never commit tokens to `.json.example` files

### 6. Document Examples
Include `example` field for complex webhooks:
```json
"example": {
  "action": "deploy",
  "environment": "production",
  "branch": "main"
}
```

---

## Related Documentation

- **Email System Details:** `docs/n8n/docs/WEBHOOK_AND_EMAIL_SYSTEM.md`
- **Google Calendar Sync:** `docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md`
- **n8n Integration:** `docs/n8n/docs/N8N_INTEGRATION.md`
- **Tool Development:** `docs/TOOL_CALLING_SYSTEM.md`
- **Agent Guidelines:** `.clinerules` (Section: Tool Development)

---

## Quick Reference

### List Webhooks
```bash
./orchestrator/orchestrator_v2.py cloud "list webhooks"
```

### Trigger Named Webhook
```bash
./jarvis "trigger slack_notify with text hello world"
```

### Trigger with Auth
```python
# In Python code
from skills.send_webhook import send_webhook

send_webhook(
    webhook="my_api",
    data={"action": "deploy"},
    headers={"Authorization": "Bearer token123"}
)
```

### Send Email
```bash
./jarvis "email boss about the meeting tomorrow at 3pm"
```

### Check Rate Limits
```bash
cat data/.webhook_rate_limit
cat data/.email_rate_limit
```

### Clear Rate Limits
```bash
rm data/.webhook_rate_limit data/.email_rate_limit
```

---

**Last Updated:** 2025-11-25  
**Version:** 1.0

