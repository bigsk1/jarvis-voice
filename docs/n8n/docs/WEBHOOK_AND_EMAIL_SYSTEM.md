# Webhook Registry & Email System

## Overview

Jarvis uses a modular webhook registry system for triggering n8n workflows and external services. This enables:

- **Named webhooks** - Reference webhooks by name instead of URL
- **Contact list** - Say "email Andrew" and Jarvis resolves the email
- **Rate limiting** - Prevents duplicate sends
- **Extensibility** - Add new webhooks without code changes

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  "Hey Jarvis, send an email to Andrew about the meeting"   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      send_email.py                          │
│  1. Look up "andrew" in config/contacts.json                │
│  2. Get webhook URL from config/webhook_registry.json       │
│  3. Check rate limit                                        │
│  4. POST to n8n webhook                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  n8n Workflow: Jarvis → Send Email (F38Tpz6OH4JqMLzW)       │
│  Webhook → Send Email (SMTP) → Respond                      │
└─────────────────────────────────────────────────────────────┘
```

## Configuration Files

### `config/webhook_registry.json`

Named webhooks with URLs, descriptions, and required fields:

```json
{
  "webhooks": {
    "send_email": {
      "url": "http://192.168.70.226:5678/webhook/jarvis-email",
      "description": "Send email via n8n SMTP",
      "required_fields": ["to", "subject", "body"],
      "rate_limit_seconds": 10
    },
    "notify_slack": {
      "url": "http://your-slack-webhook",
      "description": "Send Slack notification",
      "required_fields": ["channel", "message"],
      "enabled": false
    }
  }
}
```

### `config/contacts.json`

Contact list for email lookup:

```json
{
  "contacts": {
    "andrew": {
      "name": "Andrew",
      "email": "andrew@example.com"
    },
    "mom": {
      "name": "Mom", 
      "email": "mom@example.com"
    }
  }
}
```

## Tools

### `send_email` - High-level email tool

**Voice commands:**
- "Send an email to Andrew about the meeting"
- "Email mom and say happy birthday"
- "Send email to john@example.com with subject Hello"

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| to | string | ✓ | Contact name or email address |
| subject | string | ✓ | Email subject |
| body | string | ✓ | Email content |

**Example:**
```bash
./orchestrator/orchestrator_v2.py cloud "send email to andrew about the project update"
```

### `send_webhook` - Generic webhook tool

**Voice commands:**
- "Trigger the slack notification webhook"
- "Send webhook to home assistant"
- "List available webhooks"

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| webhook | string | * | Named webhook from registry |
| url | string | * | Direct URL (if not using name) |
| data | object | ✓ | JSON payload |

*Either `webhook` or `url` is required

**Example:**
```bash
# Using named webhook
./orchestrator/orchestrator_v2.py cloud "trigger the notify_slack webhook with message hello"

# List available webhooks
./orchestrator/orchestrator_v2.py cloud "what webhooks are available"
```

## n8n Workflow Setup

### Email Workflow

**Workflow ID:** `F38Tpz6OH4JqMLzW`  
**Webhook URL:** `http://192.168.70.226:5678/webhook/jarvis-email`

**Setup steps:**
1. Open n8n: http://192.168.70.226:5678/workflow/F38Tpz6OH4JqMLzW
2. Click the "Send Email" node
3. Add SMTP credentials (click "Create new credential")
4. Configure SMTP settings:
   - Host: Your SMTP server
   - Port: 587 (TLS) or 465 (SSL)
   - User: Your email
   - Password: Your app password
5. Save and activate the workflow

**Webhook payload:**
```json
{
  "to": "recipient@example.com",
  "subject": "Hello from Jarvis",
  "body": "This is the email content.",
  "from_name": "Jarvis Assistant"
}
```

## Adding New Webhooks

### 1. Create n8n workflow

Create a new workflow in n8n with a Webhook trigger node.

### 2. Add to registry

Edit `config/webhook_registry.json`:

```json
{
  "webhooks": {
    "my_new_webhook": {
      "url": "http://192.168.70.226:5678/webhook/my-webhook",
      "description": "What this webhook does",
      "required_fields": ["field1", "field2"],
      "rate_limit_seconds": 5,
      "enabled": true
    }
  }
}
```

### 3. Use it

```bash
# Via voice
./jarvis "Can you send an email to Boss about the project update"

# Or directly
./orchestrator/orchestrator_v2.py cloud "send email to boss with subject 'HTML Test 2' and body 'This is the updated html body"
```

## Rate Limiting

Each webhook has configurable rate limiting to prevent duplicates:

| Webhook | Default Limit |
|---------|---------------|
| send_email | 10 seconds per recipient |
| Generic webhooks | 5 seconds |

Rate limits are stored in `data/.webhook_rate_limit` and `data/.email_rate_limit`.

## Adding Contacts

Edit `config/contacts.json`:

```json
{
  "contacts": {
    "john": {
      "name": "John Smith",
      "email": "john.smith@example.com",
      "notes": "Work colleague"
    }
  }
}
```

Now you can say: "Send email to John about the project"

## Troubleshooting

### "Contact not found"
- Check `config/contacts.json` has the contact
- Contact names are case-insensitive

### "Webhook not found"  
- Check `config/webhook_registry.json`
- Ensure `enabled: true` (or omit, defaults to true)
- Ensure URL is configured

### "Rate limited"
- Wait a few seconds before retrying
- Adjust `rate_limit_seconds` in registry if needed

### Email not sending
1. Check n8n workflow is active (green toggle)
2. Verify SMTP credentials in n8n
3. Check n8n execution logs for errors
4. Test webhook directly:
```bash
curl -X POST http://192.168.70.226:5678/webhook/jarvis-email \
  -H "Content-Type: application/json" \
  -d '{"to": "test@example.com", "subject": "Test", "body": "Hello"}'
```

## Related Files

- `skills/send_email.py` - Email tool
- `skills/send_webhook.py` - Generic webhook tool
- `config/webhook_registry.json` - Webhook registry
- `config/contacts.json` - Contact list
- `docs/n8n/docs/GOOGLE_CALENDAR_SYNC.md` - Calendar sync docs

