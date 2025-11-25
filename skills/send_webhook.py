#!/usr/bin/env python3
"""
Jarvis Skill: Send Webhook
Sends POST requests to webhooks for triggering external services.

Supports:
- Named webhooks from config/webhook_registry.json (e.g., "notify_slack")
- Direct URLs (backward compatible)
- Rate limiting per webhook

Input: { "webhook": "name" OR "url": "https://...", "data": {...} }
Output: { "ok": bool, "speech": str, "data": dict }
"""
import sys
import os
import json
import time
import hashlib
import requests

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config

# Rate limit storage
RATE_LIMIT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', '.webhook_rate_limit')
DEFAULT_RATE_LIMIT = 5  # seconds


def load_webhook_registry() -> dict:
    """Load webhook registry from config/webhook_registry.json"""
    registry_file = os.path.join(os.path.dirname(__file__), '..', 'config', 'webhook_registry.json')
    try:
        with open(registry_file, 'r') as f:
            data = json.load(f)
            return data.get('webhooks', {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_webhook_url(webhook_name: str, url: str, webhooks: dict) -> tuple[str, dict]:
    """
    Resolve webhook URL from name or direct URL.
    Returns (url, webhook_config)
    """
    # If webhook name provided, look it up
    if webhook_name:
        webhook_config = webhooks.get(webhook_name)
        if not webhook_config:
            available = [k for k, v in webhooks.items() if v.get('enabled', True) and v.get('url')]
            raise ValueError(f"Webhook '{webhook_name}' not found. Available: {', '.join(available)}")
        
        if not webhook_config.get('enabled', True):
            raise ValueError(f"Webhook '{webhook_name}' is disabled")
        
        if not webhook_config.get('url'):
            raise ValueError(f"Webhook '{webhook_name}' has no URL configured")
        
        return webhook_config['url'], webhook_config
    
    # Otherwise use direct URL
    if url:
        return url, {'rate_limit_seconds': DEFAULT_RATE_LIMIT}
    
    raise ValueError("Either 'webhook' (name) or 'url' is required")


def check_rate_limit(identifier: str, limit_seconds: int) -> bool:
    """Check rate limit. Returns True if OK to proceed."""
    id_hash = hashlib.md5(identifier.encode()).hexdigest()[:8]
    
    try:
        if os.path.exists(RATE_LIMIT_FILE):
            with open(RATE_LIMIT_FILE, 'r') as f:
                limits = json.load(f)
        else:
            limits = {}
        
        last_sent = limits.get(id_hash, 0)
        now = time.time()
        
        if now - last_sent < limit_seconds:
            remaining = int(limit_seconds - (now - last_sent))
            return False, remaining
        
        # Update rate limit
        limits[id_hash] = now
        with open(RATE_LIMIT_FILE, 'w') as f:
            json.dump(limits, f)
        
        return True, 0
    except Exception:
        return True, 0


def list_available_webhooks(webhooks: dict) -> list:
    """List available webhooks for help message."""
    available = []
    for name, config in webhooks.items():
        if config.get('enabled', True) and config.get('url'):
            available.append({
                "name": name,
                "description": config.get('description', '')
            })
    return available


def main():
    """Send webhook POST request."""
    try:
        # Parse input
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    
    # Load config and registry
    load_config()
    webhooks = load_webhook_registry()
    
    # Extract parameters
    webhook_name = input_data.get("webhook")  # Named webhook from registry
    url = input_data.get("url")  # Direct URL (backward compatible)
    data = input_data.get("data", {})
    headers = input_data.get("headers", {"Content-Type": "application/json"})
    
    # Special command: list webhooks
    if webhook_name == "list" or input_data.get("list"):
        available = list_available_webhooks(webhooks)
        return_success(
            speech=f"Found {len(available)} configured webhooks",
            data={"webhooks": available}
        )
        return 0
    
    # Resolve webhook URL
    try:
        resolved_url, webhook_config = get_webhook_url(webhook_name, url, webhooks)
    except ValueError as e:
        return_error(str(e))
        return 1
    
    # Check rate limit
    rate_limit = webhook_config.get('rate_limit_seconds', DEFAULT_RATE_LIMIT)
    identifier = webhook_name or resolved_url
    ok, remaining = check_rate_limit(identifier, rate_limit)
    
    if not ok:
        return_error(f"Rate limited. Please wait {remaining} seconds before sending again.")
        return 1
    
    # Validate required fields if specified
    required_fields = webhook_config.get('required_fields', [])
    missing = [f for f in required_fields if f not in data]
    if missing:
        return_error(f"Missing required fields for this webhook: {', '.join(missing)}")
        return 1
    
    # Ensure Content-Type is set
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    
    # Send webhook
    try:
        response = requests.post(
            resolved_url,
            json=data,
            headers=headers,
            timeout=15
        )
        
        # Check response
        if 200 <= response.status_code < 300:
            webhook_display = webhook_name or resolved_url
            return_success(
                speech=f"Webhook '{webhook_display}' sent successfully",
                data={
                    "webhook": webhook_name,
                    "url": resolved_url,
                    "status_code": response.status_code,
                    "response": response.text[:200] if response.text else ""
                }
            )
            return 0
        else:
            return_error(
                speech=f"Webhook failed with status {response.status_code}",
                data={
                    "url": resolved_url,
                    "status_code": response.status_code,
                    "error": response.text[:200] if response.text else ""
                }
            )
            return 1
            
    except requests.Timeout:
        return_error("Webhook request timed out")
        return 1
    except requests.RequestException as e:
        return_error(f"Webhook request failed: {str(e)}")
        return 1
    except Exception as e:
        return_error(f"Unexpected error: {str(e)}")
        return 1


def return_success(speech, data=None):
    """Return success response."""
    result = {
        "ok": True,
        "speech": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech, data=None):
    """Return error response."""
    result = {
        "ok": False,
        "speech": speech,
        "error": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main() or 0)
