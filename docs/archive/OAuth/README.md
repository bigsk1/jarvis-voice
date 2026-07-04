# OAuth Authentication for LLM Providers

> **Status**: Research & Planning
> **Priority**: Medium (cost savings potential)
> **Last Updated**: February 2026

> [!IMPORTANT]
> **July 2026 xAI update:** Jarvis now supports Grok CLI OAuth subscription
> authentication for xAI text chat and Jarvis function calling. See
> [`../../XAI_PROVIDER.md`](../../XAI_PROVIDER.md#grok-cli-oauth-subscription).
> xAI native search, vision, image/video generation, and TTS still require an
> API key. The remaining Anthropic/Google/OpenAI material below is retained as
> historical research and is not an implementation guide.

> [!WARNING]
> This is an unimplemented research note, not a setup guide. Current Jarvis
> provider code does not read `ANTHROPIC_OAUTH_TOKEN`, Claude Code credentials,
> or Gemini CLI credentials for LLM requests. Use the API-key variables in
> `config/cloud.env.example`. Do not add the proposed tokens below expecting
> Jarvis to use subscription billing.

---

## Overview

### The Problem

Jarvis historically used **API keys** for all LLM providers. xAI text chat is
now the implemented exception; the remaining research below predates it. API
key usage means:
- Pay-per-token billing (can get expensive)
- Separate from any subscription you already have
- No way to leverage your existing Claude Pro/Max, ChatGPT Plus, or Grok Premium

### The Solution

Some providers support **OAuth authentication** that lets you use your **existing subscription** instead of API billing:

```
API Key Flow:
  You → API Key → Provider API → Pay $0.003/1K tokens

OAuth Flow:
  You → OAuth Login → Your Subscription → Usage included in $20/month
```

---

## Provider OAuth Support Summary

| Provider | OAuth Available | Subscription Includes API | Notes |
|----------|-----------------|---------------------------|-------|
| **Anthropic** | Research only | Not integrated with Jarvis | Proposed Claude Code token path below is not implemented |
| **Google** | Research only | Not integrated with Jarvis | Gemini CLI credentials are not read by Jarvis |
| **OpenAI** | ⚠️ Apps SDK | Business/Enterprise only | "Sign in with ChatGPT" for MCP apps |
| **xAI** | ✅ Grok CLI | Text/tool subscription path | Implemented; specialized APIs remain API-key-only |

**Historical finding (Feb 2026):** This table predated xAI's Grok CLI OAuth
integration. Current Jarvis behavior is documented in `docs/XAI_PROVIDER.md`.

---

## What Subscription OAuth Covers vs API Keys

### Important Distinction

Subscription OAuth typically covers **chat/completions** (the main LLM), but **specialized APIs** (image gen, video gen, embeddings) often still require separate API billing.

### Coverage Matrix

| Feature | Anthropic OAuth | Google OAuth | Notes |
|---------|-----------------|--------------|-------|
| **Chat/Completions** | ✅ Included | ✅ Included | Main LLM Q&A |
| **Tool Use/Function Calling** | ✅ Included | ✅ Included | Agent capabilities |
| **Image Generation** | N/A | ⚠️ Via AI Credits | Anthropic has no image gen |
| **Video Generation** | N/A | ❓ Unknown | Anthropic has no video gen |
| **Embeddings** | ❓ Unknown | ⚠️ Maybe | Often separate API |
| **Audio/TTS** | N/A | ❓ Unknown | Provider dependent |

### For Jarvis Specifically

| Jarvis Feature | Provider | OAuth Works? | Notes |
|----------------|----------|--------------|-------|
| **LLM Q&A** | Anthropic | ✅ YES | Claude Code OAuth |
| **LLM Q&A** | Google | ✅ YES | Gemini CLI auth |
| **Tool Calling** | Anthropic | ✅ YES | Messages API supports tools |
| **Tool Calling** | Google | ✅ YES | Gemini supports tools |
| **Image Generation** | Google Gemini | ⚠️ Maybe | Uses AI Credits pool |
| **Image Generation** | OpenAI DALL-E | ❌ NO | API key required |
| **Image Generation** | xAI Grok | ❌ NO | API key required |
| **Video Generation** | xAI | ❌ NO | API key required |

### Recommended Strategy: Hybrid Auth

Use **OAuth for main LLM** (biggest cost saver) + **API keys for specialized features**:

```python
def get_auth_for_task(provider: str, task: str) -> dict:
    """Get appropriate auth based on task type."""

    if task in ['chat', 'completion', 'tool_use', 'agent']:
        # Try OAuth first for main LLM tasks
        oauth = get_oauth_token(provider)
        if oauth:
            return {'type': 'oauth', 'token': oauth}

    # Image/video/embeddings - use API key
    if task in ['image_generation', 'video_generation', 'embeddings']:
        api_key = get_api_key(provider)
        return {'type': 'api_key', 'token': api_key}

    # Default fallback
    return {'type': 'api_key', 'token': get_api_key(provider)}
```

### Cost Savings Reality Check

| Use Case | OAuth Savings | Still Needs API Key |
|----------|---------------|---------------------|
| Heavy Claude chat user | ✅ High ($50+/mo) | - |
| Heavy Gemini chat user | ✅ Medium ($20-40/mo) | - |
| Image generation (DALL-E/xAI) | ❌ None | Yes, API billing |
| Video generation (xAI) | ❌ None | Yes, API billing |
| Mixed usage | ✅ Partial | Specialized APIs |

**Bottom Line**: OAuth subscription access is most valuable for **LLM chat/completions** - where most costs are. Specialized features like image/video gen typically still need API keys.

---

## Anthropic OAuth (Claude Pro/Max)

### How It Works

Anthropic provides `claude setup-token` command that:
1. Opens browser to `claude.ai/oauth/authorize`
2. You log in with your Claude Pro/Max account
3. Generates an OAuth token (format: `<your-claude-oauth-token>`)
4. Token valid for **1 year**
5. Usage counts against your subscription quota

### Token Format

| Type | Format | Source |
|------|--------|--------|
| API Key | `<your-anthropic-api-key>` | Console (pay-per-token) |
| OAuth Token | `<your-claude-oauth-token>` | CLI OAuth (subscription) |

Doc placeholders above are intentionally non-key-shaped (no `sk-ant-…` samples) to
avoid secret scanners; real tokens use provider-specific prefixes at runtime.

### Current Implementation (Claude Code)

```bash
# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Generate OAuth token from subscription
claude setup-token

# Token saved to environment
export CLAUDE_CODE_OAUTH_TOKEN=<your-claude-oauth-token>
```

### What Claude Code OAuth Supports

Per [Anthropic's docs](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan):

| API Feature | Supported via OAuth |
|-------------|---------------------|
| Messages API (chat) | ✅ Yes |
| Tool Use / Function Calling | ✅ Yes |
| Extended thinking | ✅ Yes |
| All Claude models | ✅ Yes |

**Important**: If `ANTHROPIC_API_KEY` is set, Claude Code uses API billing instead of subscription. For Jarvis, we'd want OAuth to take priority.

### For Jarvis Integration

**Priority**: This is the most valuable OAuth to implement since:
- Anthropic has the most complete OAuth support
- Claude Pro ($20/month) or Max ($100/month) includes substantial usage
- Many Jarvis users likely already have Claude subscriptions
- Tool use IS supported via OAuth (critical for Jarvis agents)

---

## xAI / Grok (Implemented July 2026)

### Current Status

xAI's official Grok CLI caches an OAuth session in `~/.grok/auth.json` and
documents access to its CLI chat proxy. Jarvis now uses that path for text chat
and Jarvis function calling through `XAI_AUTH_MODE=oauth` (or `auto` with a
blank key).

```bash
# config/cloud.env
XAI_AUTH_MODE=oauth
XAI_OAUTH_MODEL=grok-build
XAI_API_KEY=""
```

### Subscription vs API

| Product | Access Type | Billing |
|---------|-------------|---------|
| Grok CLI OAuth | Jarvis text chat + function calls | Subscription limits |
| Grok API | Native search, vision, media, TTS, API chat | API-key billing |

**Boundary**: OAuth does not authorize xAI native search, vision, image/video,
or TTS endpoints. Those still need `XAI_API_KEY`.

### Free Credits

xAI offers free API credits:
- **$25/month** for all developers
- **$150/month** for teams spending $5+/month (with data sharing opt-in)

---

## Google Gemini CLI (Google AI Pro/Ultra)

### How It Works

Google's Gemini CLI supports **"Login with Google"** authentication that uses your subscription:

```bash
# Install Gemini CLI (choose one)
npm install -g @google/gemini-cli   # NPM (Node.js 20+)
brew install gemini-cli             # Homebrew
npx @google/gemini-cli              # No install, runs directly

# Login with Google account (opens browser)
gemini auth login

# If you're a Google AI Pro/Ultra subscriber, usage counts against subscription
```

### Authentication Methods

| Method | Command | Billing |
|--------|---------|---------|
| **Login with Google** | `gemini auth login` | Subscription (if Pro/Ultra) |
| **API Key** | `export GEMINI_API_KEY=<your-gemini-api-key>` | Pay-per-token |
| **Vertex AI ADC** | `gcloud auth application-default login` | GCP billing |

### Subscription Tiers

| Tier | Price | API Access |
|------|-------|------------|
| Free | $0 | Limited via web |
| Google AI Plus | $7.99/month | Includes API credits |
| Google AI Pro/Ultra | Higher tiers | Full API access via OAuth |

### For Jarvis Integration

```python
# Check for Google OAuth token first
def get_gemini_auth():
    # 1. Check for OAuth credentials (from `gemini auth login`)
    oauth_creds = Path.home() / '.config' / 'gemini' / 'credentials.json'
    if oauth_creds.exists():
        return {'type': 'oauth', 'billing': 'subscription'}

    # 2. Fall back to API key
    api_key = get_config_value('GOOGLE_GEMINI_API_KEY')
    if api_key:
        return {'type': 'api_key', 'billing': 'api'}
```

---

## OpenAI Apps SDK (Business/Enterprise)

### Current Status

OpenAI has **"Sign in with ChatGPT"** OAuth via their Apps SDK, but it's primarily for:
- Business/Enterprise building internal MCP apps
- Developers creating apps that users authenticate into
- NOT for individual ChatGPT Plus users to get API access

### How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Your App   │ ──► │ Sign in with     │ ──► │ User's      │
│  (MCP)      │     │ ChatGPT (OAuth)  │     │ ChatGPT     │
└─────────────┘     └──────────────────┘     │ Account     │
                                              └─────────────┘
                                                    │
                                                    ▼
                            User's subscription credits fund API calls
```

### Requirements

1. **Business/Enterprise/Edu ChatGPT plan** (not Plus)
2. **Register app** in OpenAI developer platform
3. **Developer mode** enabled by workspace admin
4. **MCP server endpoint** configured

### Apps SDK Features

- OAuth 2.1 + OIDC standards
- Model Context Protocol (MCP) support
- User consent and token management
- Access to GPT-4 via user's subscription

### Limitations for Jarvis

| ChatGPT Tier | OAuth Available | API Access |
|--------------|-----------------|------------|
| Plus ($20/month) | ❌ No | API key only (separate billing) |
| Pro ($200/month) | ⚠️ Maybe | Includes API credits + possible OAuth |
| Business | ✅ Yes | Via Apps SDK |
| Enterprise | ✅ Yes | Via Apps SDK |

**For most individual users**: ChatGPT Plus does NOT provide OAuth API access. You need Business tier or higher.

### Future Possibility

OpenAI may expand "Sign in with ChatGPT" to Plus subscribers. The Apps SDK infrastructure exists - it's just not enabled for consumer tiers yet.

---

## Implementation Plan for Jarvis

### Phase 1: Anthropic OAuth (Highest Value)

#### Config Structure

```json
// config/oauth.json
{
  "anthropic": {
    "enabled": true,
    "token": null,
    "expires_at": null,
    "token_type": "oauth"
  },
  "xai": {
    "enabled": false,
    "notes": "No OAuth available - uses API keys only"
  },
  "openai": {
    "enabled": false,
    "notes": "OAuth exists but doesn't provide subscription API access"
  }
}
```

#### Environment Variable Fallback

```bash
# In cloud.env - API key (fallback)
ANTHROPIC_API_KEY=<your-anthropic-api-key>

# OAuth token (if set, takes priority)
ANTHROPIC_OAUTH_TOKEN=<your-claude-oauth-token>
```

#### Provider Selection Logic

```python
def get_anthropic_auth():
    """Get Anthropic authentication, preferring OAuth over API key."""

    # 1. Check OAuth token first (subscription-based)
    oauth_token = get_config_value('ANTHROPIC_OAUTH_TOKEN')
    if oauth_token and oauth_token.startswith('sk-ant-oat'):
        return {
            'type': 'oauth',
            'token': oauth_token,
            'billing': 'subscription'
        }

    # 2. Fall back to API key (pay-per-token)
    api_key = get_config_value('ANTHROPIC_API_KEY')
    if api_key:
        return {
            'type': 'api_key',
            'token': api_key,
            'billing': 'api'
        }

    return None
```

### Phase 2: OAuth Setup Script

Create `bin/anthropic-auth` similar to existing `bin/spotify-auth`:

```python
#!/usr/bin/env python3
"""
Anthropic OAuth Setup for Claude Pro/Max Subscription

Uses your Claude subscription instead of API billing.
"""

import webbrowser
import sys

# OAuth endpoints
AUTH_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://claude.ai/oauth/token"

def main():
    print("=" * 60)
    print("Anthropic OAuth Setup for Jarvis")
    print("=" * 60)
    print()
    print("This will connect Jarvis to your Claude Pro/Max subscription.")
    print("Usage will count against your subscription quota, NOT API billing.")
    print()

    # Check for existing token
    existing = get_config_value('ANTHROPIC_OAUTH_TOKEN')
    if existing and existing.startswith('sk-ant-oat'):
        print(f"✅ OAuth token already configured: {existing[:20]}...")
        print("   To re-authenticate, delete ANTHROPIC_OAUTH_TOKEN from config")
        return

    print("📋 Instructions:")
    print("   1. Browser will open to Claude login")
    print("   2. Log in with your Claude Pro/Max account")
    print("   3. Authorize Jarvis")
    print("   4. Copy the redirect URL and paste below")
    print()

    # For localhost without HTTPS, use manual code entry
    # (Same approach as Spotify OAuth)

    auth_params = {
        'client_id': 'jarvis-voice-assistant',  # Would need to register
        'redirect_uri': 'http://127.0.0.1:8889/callback',
        'response_type': 'code',
        'scope': 'model:read model:write'
    }

    full_url = f"{AUTH_URL}?{'&'.join(f'{k}={v}' for k,v in auth_params.items())}"

    print(f"Opening: {full_url[:50]}...")
    webbrowser.open(full_url)

    print()
    print("After authorizing, paste the redirect URL here:")
    redirect_url = input("URL: ").strip()

    # Extract code from URL
    # ... token exchange logic ...
```

### Localhost / Non-HTTPS Handling

Since Jarvis runs locally without HTTPS, we use the same approach as Spotify:

1. **Manual URL Paste**: User copies the redirect URL from browser and pastes it
2. **Local Callback Server**: Temporarily spin up `http://127.0.0.1:8889/callback`
3. **Out-of-Band Flow**: Some providers support `urn:ietf:wg:oauth:2.0:oob` for CLI apps

```python
# Option 1: Manual paste (like current Spotify flow)
print("Paste the redirect URL:")
url = input()
code = parse_code_from_url(url)

# Option 2: Local callback server
from http.server import HTTPServer, BaseHTTPRequestHandler

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Extract code from query params
        code = parse_qs(urlparse(self.path).query).get('code', [None])[0]
        # ... exchange for token ...

server = HTTPServer(('127.0.0.1', 8889), OAuthCallbackHandler)
server.handle_request()  # Handle single request then stop
```

---

## Token Management

### Storage

```
data/
├── .spotify_cache          # Existing Spotify OAuth
├── .anthropic_oauth.json   # New: Anthropic OAuth token
└── .oauth_tokens.json      # Future: Unified token store
```

### Token Refresh

| Provider | Token Lifetime | Refresh |
|----------|----------------|---------|
| Spotify | 1 hour | Auto-refresh with refresh_token |
| Anthropic OAuth | 1 year | Manual re-auth |

### Token Invalidation

Tokens can be invalidated by:
- User revokes access in provider settings
- Password change
- Subscription cancellation
- Token expiry

Handle gracefully:
```python
def call_anthropic(prompt):
    try:
        response = client.messages.create(...)
    except AuthenticationError as e:
        if 'invalid_token' in str(e):
            print("OAuth token invalid. Re-authentication helper is not implemented")
            # Fall back to API key if available
            return call_with_api_key(prompt)
        raise
```

---

## Registering Jarvis as OAuth App

### Anthropic

**Status**: Need to investigate if Anthropic allows third-party OAuth app registration.

Claude Code uses Anthropic's first-party OAuth. For Jarvis, we'd need:
1. Register at Anthropic Developer Console
2. Get `client_id` and `client_secret`
3. Configure redirect URIs (including `http://127.0.0.1:*` for local)

### Alternative: Use Claude Code's Token

Since `claude setup-token` already works, we could:
1. Have users run `claude setup-token`
2. Copy the generated token to Jarvis config
3. Use it directly (both are just Bearer tokens)

```bash
# User runs Claude Code's auth
claude setup-token

# Copy token to Jarvis
echo "ANTHROPIC_OAUTH_TOKEN=<your-claude-oauth-token>" >> config/cloud.env
```

---

## Using Provider CLIs for OAuth Tokens

Many apps (like Cursor, OpenCode, Claw) use the **provider's own CLI tools** to obtain OAuth tokens rather than implementing OAuth from scratch. This is the simplest approach:

### Provider CLI Commands

| Provider | CLI | OAuth Command | Token Location |
|----------|-----|---------------|----------------|
| **Anthropic** | Claude Code | `claude setup-token` | `CLAUDE_CODE_OAUTH_TOKEN` env var |
| **Google** | Gemini CLI | `gemini auth login` | `~/.config/gemini/credentials.json` |
| **OpenAI** | (none for consumers) | N/A | API keys only |
| **xAI** | Grok CLI | `grok login` | `~/.grok/auth.json` |

### Strategy: Piggyback on Provider CLIs

Instead of implementing full OAuth flows, Jarvis can:

1. **Detect if provider CLI is installed**
2. **Check for existing OAuth tokens** from CLI auth
3. **Use those tokens** for API calls
4. **Fall back to API keys** if no OAuth token

```python
def get_provider_auth(provider: str):
    """Get auth, preferring OAuth tokens from provider CLIs."""

    if provider == 'anthropic':
        # Check for Claude Code OAuth token
        oauth_token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN')
        if not oauth_token:
            # Check common locations
            oauth_token = read_token_file('~/.claude/oauth_token')

        if oauth_token and oauth_token.startswith('sk-ant-oat'):
            return {'type': 'oauth', 'token': oauth_token}

    elif provider == 'google':
        # Check for Gemini CLI credentials
        creds_path = Path.home() / '.config' / 'gemini' / 'credentials.json'
        if creds_path.exists():
            return {'type': 'oauth', 'credentials': creds_path}

    # Fall back to API key
    api_key = get_config_value(f'{provider.upper()}_API_KEY')
    return {'type': 'api_key', 'token': api_key} if api_key else None
```

### Benefits of This Approach

1. **No OAuth app registration** - Use provider's existing apps
2. **Users already have tokens** - If using Claude Code or Gemini CLI
3. **Simple implementation** - Just read existing token files
4. **Graceful fallback** - API keys work if no OAuth

### Setup Instructions for Users

```bash
# For Anthropic (Claude Pro/Max subscribers)
npm install -g @anthropic-ai/claude-code
claude setup-token
# Token automatically available for Jarvis

# For Google (AI Pro/Ultra subscribers)
npm install -g @google/gemini-cli
gemini auth login
# Credentials saved for Jarvis to use
```

---

## UI Integration (Web UI)

### Settings Panel

Add OAuth section to Settings → API Keys tab:

```
┌─────────────────────────────────────────────────┐
│  API Keys                                        │
├─────────────────────────────────────────────────┤
│  Anthropic                                       │
│  ┌───────────────────────────────────────────┐  │
│  │ ○ API Key     <anthropic-api-key>         │  │
│  │ ● OAuth       <claude-oauth-token> ✓ Active  │  │
│  │               [Disconnect] [Refresh]       │  │
│  │               Billing: Subscription        │  │
│  └───────────────────────────────────────────┘  │
│                                                  │
│  xAI                                             │
│  ┌───────────────────────────────────────────┐  │
│  │ ○ API Key     <xai-api-key>               │  │
│  │ ● OAuth       Grok CLI session ✓ Active   │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### Status Indicators

| Status | Display |
|--------|---------|
| OAuth active | 🟢 `Using subscription (OAuth)` |
| API Key active | 🟡 `Using API key (pay-per-token)` |
| OAuth expired | 🔴 `OAuth expired - click to refresh` |
| Not configured | ⚪ `Not configured` |

---

## Cost Comparison

### Typical Usage (Heavy User)

| Provider | API Key Cost | With Subscription |
|----------|--------------|-------------------|
| **Anthropic** | ~$50-100/month | $20/month (Pro) or $100/month (Max) |
| **xAI** | Provider-dependent | Grok subscription limits for OAuth text chat |
| **OpenAI** | ~$40-80/month | Same (no OAuth for API) |

### Break-Even Analysis

**Anthropic OAuth is valuable if:**
- You use Claude heavily (>1M tokens/month)
- You already have Claude Pro/Max for web use
- You want predictable billing

---

## Implementation Checklist

### Phase 1: Research & Planning ✅
- [x] Research provider OAuth support
- [x] Document findings
- [x] Identify providers with subscription OAuth (Anthropic, Google)
- [x] Document OpenAI Apps SDK limitations
- [x] Document provider CLI token approach

### Phase 2: Provider CLI Token Detection (Quick Win)
- [ ] Detect `CLAUDE_CODE_OAUTH_TOKEN` environment variable
- [ ] Check for Gemini CLI credentials at `~/.config/gemini/credentials.json`
- [ ] Add fallback logic: OAuth token → API key
- [ ] Test with Claude Pro subscription
- [ ] Test with Google AI Pro subscription

### Phase 3: Anthropic OAuth Script
- [ ] Create `bin/anthropic-auth` script (like `bin/spotify-auth`)
- [ ] Add `ANTHROPIC_OAUTH_TOKEN` to cloud.env.example
- [ ] Handle localhost callback (manual URL paste)
- [ ] Test token refresh/expiry

### Phase 4: Google OAuth Script
- [ ] Create `bin/gemini-auth` script
- [ ] Integrate with Gemini CLI or implement native OAuth
- [ ] Store credentials in `data/.gemini_oauth.json`

### Phase 5: UI Integration
- [ ] Add OAuth section to web UI Settings → API Keys
- [ ] Show OAuth vs API key status per provider
- [ ] Add "Connect with Subscription" buttons
- [ ] Handle token invalidation gracefully
- [ ] Show billing type indicator (subscription vs pay-per-token)

### Phase 6: Documentation
- [ ] Update cloud.env.example with OAuth token vars
- [ ] Add quick setup guide for each provider
- [ ] Document cost savings comparison

---

## Related Files

| File | Purpose |
|------|---------|
| `bin/spotify-auth` | Reference implementation for OAuth CLI flow |
| `skills/spotify.py` | How Spotify OAuth tokens are used |
| `data/.spotify_cache` | Token storage format |
| `lib/llm_provider.py` | Where provider auth would need to be implemented |
| `config/cloud.env` | Where tokens/keys are stored |

---

## References

- [Anthropic Claude Code Auth](https://support.anthropic.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
- [xAI API Docs](https://docs.x.ai/docs/overview)
- [OpenAI Auth Docs](https://developers.openai.com/apps-sdk/build/auth/)
- [Google Gemini OAuth](https://ai.google.dev/gemini-api/docs/oauth)

---

## Summary

### Providers with Subscription OAuth

| Provider | Method | Subscription Tier | Status |
|----------|--------|-------------------|--------|
| **Anthropic** | `claude setup-token` | Pro ($20) / Max ($100) | ✅ Ready to use |
| **Google** | `gemini auth login` | AI Pro / AI Ultra | ✅ Ready to use |
| **OpenAI** | Apps SDK | Business/Enterprise only | ⚠️ Not for consumers |
| **xAI** | `grok login` | Grok subscription | ✅ Implemented for text/tool calls |

### Proposed Setup (Not Implemented)

The commands below were retained as design input only. They do not configure
the current Jarvis provider implementation.

**Anthropic concept:**
```bash
# 1. Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# 2. Get OAuth token from your Pro/Max subscription
claude setup-token

# 3. Add to Jarvis config
echo "ANTHROPIC_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN" >> config/cloud.env
```

**For Google users:**
```bash
# 1. Install Gemini CLI
npm install -g @google/gemini-cli

# 2. Login with Google account (AI Pro/Ultra)
gemini auth login

# Jarvis can read credentials from ~/.config/gemini/
```

### Recommended Implementation Order

1. **Anthropic** - Most users have Claude, clear OAuth path
2. **Google** - Gemini CLI provides easy OAuth
3. **OpenAI** - Only if targeting Business/Enterprise users
4. **xAI** - Implemented for Grok CLI OAuth text/tool calls in July 2026

### Cost Savings Potential

| Provider | API Cost (Heavy Use) | With Subscription |
|----------|---------------------|-------------------|
| Anthropic | ~$50-100/month | $20/month (Pro) |
| Google | ~$40-80/month | $7.99/month (Plus) |

**Bottom Line**: If you're a Claude Pro/Max or Google AI Pro subscriber, OAuth can save significant money by using your subscription instead of API billing.
