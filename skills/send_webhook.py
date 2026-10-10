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
import hashlib
import json
import math
import os
import re
import sys
import time

import requests
from jsonschema import SchemaError, ValidationError
from jsonschema.validators import validator_for

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import get_config_value, load_config

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


def substitute_env_vars(value: str) -> str:
    """
    Substitute environment variables in a trusted registry string.
    Supports ${VAR_NAME} syntax, looks in config first, then os.environ.

    Do not call this with tool-supplied values. process_headers enforces that
    boundary for request headers.
    """
    pattern = r'\$\{([^}]+)\}'
    
    def replacer(match):
        var_name = match.group(1)
        # Try config_loader first (handles cloud.env/local.env)
        config_val = get_config_value(var_name)
        if config_val:
            return config_val
        # Fall back to os.environ
        return os.environ.get(var_name, match.group(0))
    
    return re.sub(pattern, replacer, value)


def validate_request_headers(request_headers: dict) -> None:
    """Reject environment lookups selected by an untrusted tool call."""
    for value in request_headers.values():
        if isinstance(value, str) and re.search(r'\$\{[^}]+\}', value):
            raise ValueError(
                "Environment-variable placeholders are only allowed in "
                "config/webhook_registry.json headers"
            )


def process_headers(webhook_config: dict, request_headers: dict) -> dict:
    """
    Merge headers from webhook config with request headers.
    Request headers take precedence. Environment placeholders are resolved only
    in the operator-managed webhook registry, never in tool-call arguments.
    """
    validate_request_headers(request_headers)

    # Start with registry headers
    merged = {}
    registry_headers = webhook_config.get('headers', {})
    
    for key, value in registry_headers.items():
        if isinstance(value, str):
            merged[key] = substitute_env_vars(value)
        else:
            merged[key] = value
    
    # Override with request headers (they take precedence)
    for key, value in request_headers.items():
        merged[key] = value
    
    return merged


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
        
        # TODO: Do we pass everysingle var in the config to the webhook?
        return substitute_env_vars(webhook_config['url']), webhook_config
    
    # Otherwise use direct URL
    if url:
        return url, {'rate_limit_seconds': DEFAULT_RATE_LIMIT}
    
    raise ValueError("Either 'webhook' (name) or 'url' is required")


def check_rate_limit(identifier: str, limit_seconds: int) -> tuple[bool, int]:
    """Reserve an outbound attempt after local validation; return retry seconds."""
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
            remaining = math.ceil(limit_seconds - (now - last_sent))
            return False, remaining
        
        # Update rate limit
        limits[id_hash] = now
        with open(RATE_LIMIT_FILE, 'w') as f:
            json.dump(limits, f)
        
        return True, 0
    except Exception:
        return True, 0


def payload_contract(webhook_config: dict) -> dict:
    """Expose operator-supplied payload guidance, without URLs or credentials."""
    contract = {"required_fields": webhook_config.get("required_fields", [])}
    for key in ("payload_schema", "example", "optional_fields", "notes"):
        if key in webhook_config:
            contract[key] = webhook_config[key]
    return contract


def list_available_webhooks(webhooks: dict) -> list:
    """List available webhooks for help message."""
    available = []
    for name, config in webhooks.items():
        if config.get('enabled', True) and config.get('url'):
            available.append({
                "name": name,
                "description": config.get('description', ''),
                **payload_contract(config),
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

    if not isinstance(data, dict) or not isinstance(headers, dict):
        return_error("data and headers must be JSON objects", data={"request_sent": False})
        return 1

    # Reject caller-selected environment lookups before URL resolution, DNS,
    # rate-limit writes, or any outbound request can occur.
    try:
        validate_request_headers(headers)
    except ValueError as e:
        return_error(str(e))
        return 1
    
    # Special command: list webhooks
    if webhook_name == "list" or input_data.get("list"):
        available = list_available_webhooks(webhooks)
        return_success(
            speech=f"Found {len(available)} configured webhooks",
            data={"webhooks": available, "request_sent": False}
        )
        return 0
    
    # Resolve webhook URL
    try:
        resolved_url, webhook_config = get_webhook_url(webhook_name, url, webhooks)
    except ValueError as e:
        return_error(str(e))
        return 1

    if input_data.get('describe'):
        if not webhook_name:
            return_error('describe requires a named webhook', data={'request_sent': False})
            return 1
        return_success(
            speech=f"Payload contract for '{webhook_name}'; no webhook was sent",
            data={'webhook': webhook_name, 'description': webhook_config.get('description', ''),
                  'request_sent': False, **payload_contract(webhook_config)},
        )
        return 0
    
    # SECURITY: If using direct URL (not registry), validate for SSRF
    if url and not webhook_name:
        try:
            from stash_helper import SecurityError, validate_url
        except ImportError:
            return_error("URL security validation unavailable; webhook was not sent")
            return 1
        try:
            validate_url(resolved_url)
        except SecurityError as e:
            return_error(f"URL blocked for security: {e}. Use a named webhook from registry instead.")
            return 1
    
    # Validate required fields if specified
    required_fields = webhook_config.get('required_fields', [])
    missing = [f for f in required_fields if f not in data]
    if missing:
        return_error(
            f"Missing required fields for this webhook: {', '.join(missing)}. No webhook was sent.",
            data={"webhook": webhook_name, "request_sent": False, "missing_fields": missing, **payload_contract(webhook_config)},
        )
        return 1

    # Per-destination contracts remain in the trusted registry, not this tool.
    if "payload_schema" in webhook_config:
        try:
            schema = webhook_config["payload_schema"]
            if not isinstance(schema, (dict, bool)):
                raise SchemaError("Expected an object or boolean schema")
            validator = validator_for(schema)
            validator.check_schema(schema)
            validator(schema).validate(data)
        except SchemaError:
            return_error("Invalid payload_schema in webhook registry", data={"request_sent": False})
            return 1
        except ValidationError as e:
            path = ".".join(str(part) for part in e.absolute_path) or "data"
            return_error(
                f"Invalid webhook payload at {path}: {e.message}. No webhook was sent.",
                data={"webhook": webhook_name, "request_sent": False, "validation_path": path, **payload_contract(webhook_config)},
            )
            return 1
    
    # Only trusted registry headers may resolve environment placeholders.
    try:
        merged_headers = process_headers(webhook_config, headers)
    except ValueError as e:
        return_error(str(e))
        return 1
    
    # Ensure Content-Type is set
    if "Content-Type" not in merged_headers:
        merged_headers["Content-Type"] = "application/json"

    # Only attempts ready to reach the endpoint consume the cooldown.
    rate_limit = webhook_config.get('rate_limit_seconds', DEFAULT_RATE_LIMIT)
    identifier = webhook_name or resolved_url
    ok, remaining = check_rate_limit(identifier, rate_limit)
    if not ok:
        unit = "second" if remaining == 1 else "seconds"
        return_error(
            f"Rate limited. Please wait {remaining} {unit} before sending again. No webhook was sent.",
            data={"webhook": webhook_name, "request_sent": False, "retry_after_seconds": remaining},
        )
        return 1
    
    # Send webhook
    try:
        response = requests.post(
            resolved_url,
            json=data,
            headers=merged_headers,
            timeout=15,
            allow_redirects=False,
        )

        if 300 <= response.status_code < 400:
            return_error(
                speech=(
                    f"Webhook 3xx response refused for security (status {response.status_code}). "
                    "Configure the webhook to return its final response directly."
                ),
                data={
                    "webhook": webhook_name,
                    "url": resolved_url,
                    "status_code": response.status_code,
                    "redirect_blocked": True,
                    "request_sent": True,
                    "response_received": True,
                    "delivery_status": "redirect_refused",
                    "retry_safe": False,
                },
            )
            return 1
        
        # Check response
        if 200 <= response.status_code < 300:
            webhook_display = webhook_name or resolved_url
            return_success(
                speech=(f"Webhook '{webhook_display}' delivered (HTTP {response.status_code}). "
                        "HTTP acceptance alone does not verify the automation's result."),
                data={
                    "webhook": webhook_name,
                    "url": resolved_url,
                    "status_code": response.status_code,
                    "response": response.text[:200] if response.text else "",
                    "request_sent": True,
                    "response_received": True,
                    "delivery_status": "accepted",
                }
            )
            return 0
        else:
            return_error(
                speech=f"Webhook failed with status {response.status_code}",
                data={
                    "url": resolved_url,
                    "status_code": response.status_code,
                    "error": response.text[:200] if response.text else "",
                    "webhook": webhook_name,
                    "request_sent": True,
                    "response_received": True,
                    "delivery_status": "rejected",
                    "retry_safe": False,
                }
            )
            return 1
            
    except requests.Timeout:
        return_error(
            "Webhook request timed out; it may have reached the destination. Check its state before retrying.",
            data={'webhook': webhook_name, 'request_sent': None, 'response_received': False,
                  'delivery_status': 'unknown', 'retry_safe': False},
        )
        return 1
    except requests.RequestException as e:
        return_error(
            f"Webhook request failed: {str(e)}. Delivery is unknown; check the destination before retrying.",
            data={'webhook': webhook_name, 'request_sent': None, 'response_received': False,
                  'delivery_status': 'unknown', 'retry_safe': False},
        )
        return 1
    except Exception as e:
        return_error(
            f"Unexpected webhook error: {str(e)}. Delivery is unknown; check the destination before retrying.",
            data={'webhook': webhook_name, 'request_sent': None, 'response_received': False,
                  'delivery_status': 'unknown', 'retry_safe': False},
        )
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
    result["data"] = {"request_sent": False, **(data or {})}
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main() or 0)
