#!/usr/bin/env python3
"""
Jarvis Skill: Send Email
Send emails via n8n SMTP webhook. Resolves contact names to email addresses.

Input: { "to": "andrew" or "andrew@email.com", "subject": "...", "body": "..." }
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
from config_loader import load_config, get_config_value

# Rate limit storage (simple file-based)
RATE_LIMIT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', '.email_rate_limit')
RATE_LIMIT_SECONDS = 10  # Minimum seconds between emails to same recipient


def load_contacts() -> dict:
    """Load contacts from config/contacts.json"""
    contacts_file = os.path.join(os.path.dirname(__file__), '..', 'config', 'contacts.json')
    try:
        with open(contacts_file, 'r') as f:
            data = json.load(f)
            return data.get('contacts', {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_webhook_registry() -> dict:
    """Load webhook registry from config/webhook_registry.json"""
    registry_file = os.path.join(os.path.dirname(__file__), '..', 'config', 'webhook_registry.json')
    try:
        with open(registry_file, 'r') as f:
            data = json.load(f)
            return data.get('webhooks', {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def resolve_email(to: str, contacts: dict) -> tuple[str, str]:
    """
    Resolve a name or email to actual email address.
    Returns (email, display_name)
    """
    # If it looks like an email, use it directly
    if '@' in to:
        return to, to.split('@')[0]
    
    # Try to find in contacts (case-insensitive)
    to_lower = to.lower().strip()
    for key, contact in contacts.items():
        if key.lower() == to_lower or contact.get('name', '').lower() == to_lower:
            return contact['email'], contact.get('name', key)
    
    return None, to


def check_rate_limit(email: str) -> bool:
    """Check if we're rate limited for this email. Returns True if OK to send."""
    email_hash = hashlib.md5(email.encode()).hexdigest()[:8]
    
    try:
        if os.path.exists(RATE_LIMIT_FILE):
            with open(RATE_LIMIT_FILE, 'r') as f:
                limits = json.load(f)
        else:
            limits = {}
        
        last_sent = limits.get(email_hash, 0)
        now = time.time()
        
        if now - last_sent < RATE_LIMIT_SECONDS:
            return False
        
        # Update rate limit
        limits[email_hash] = now
        with open(RATE_LIMIT_FILE, 'w') as f:
            json.dump(limits, f)
        
        return True
    except Exception:
        return True  # Allow on error


def send_email_webhook(to: str, subject: str, body: str, webhook_url: str, 
                       image_url: str = None, link_url: str = None, link_text: str = None) -> dict:
    """Send email via n8n webhook
    
    Args:
        to: Recipient email
        subject: Email subject
        body: Email body text
        webhook_url: n8n webhook URL
        image_url: Optional image URL to embed (e.g., album art)
        link_url: Optional link URL (e.g., Spotify link)
        link_text: Optional link display text
    """
    payload = {
        "to": to,
        "subject": subject,
        "body": body,
        "from_name": "Jarvis Assistant"
    }
    
    # Add optional rich content
    if image_url:
        payload["image_url"] = image_url
    if link_url:
        payload["link_url"] = link_url
        payload["link_text"] = link_text or "Open Link"
    
    response = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    
    return {
        "status_code": response.status_code,
        "ok": 200 <= response.status_code < 300,
        "response": response.text[:200] if response.text else ""
    }


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Extract parameters
        to = args.get('to')
        subject = args.get('subject')
        body = args.get('body')
        image_url = args.get('image_url')  # Optional: image to embed (e.g., album art)
        link_url = args.get('link_url')    # Optional: clickable link
        link_text = args.get('link_text')  # Optional: link display text
        
        # Validate required fields
        if not to:
            raise ValueError("'to' (recipient name or email) is required")
        if not subject:
            raise ValueError("'subject' is required")
        if not body:
            raise ValueError("'body' (email content) is required")
        
        # Load contacts and webhook registry
        contacts = load_contacts()
        webhooks = load_webhook_registry()
        
        # Resolve recipient
        email, display_name = resolve_email(to, contacts)
        if not email:
            # List available contacts
            available = list(contacts.keys())
            raise ValueError(f"Contact '{to}' not found. Available contacts: {', '.join(available) if available else 'none configured'}")
        
        # Get webhook URL
        email_webhook = webhooks.get('send_email', {})
        webhook_url = email_webhook.get('url')
        
        if not webhook_url:
            raise ValueError("Email webhook not configured in config/webhook_registry.json")
        
        # Check rate limit
        if not check_rate_limit(email):
            print(json.dumps({
                "ok": False,
                "error": "rate_limited",
                "speech": f"Please wait a few seconds before sending another email to {display_name}"
            }))
            sys.exit(1)
        
        # Send email
        result = send_email_webhook(
            email, subject, body, webhook_url,
            image_url=image_url, link_url=link_url, link_text=link_text
        )
        
        if result['ok']:
            print(json.dumps({
                "ok": True,
                "speech": f"Email sent to {display_name}",
                "data": {
                    "to": email,
                    "to_name": display_name,
                    "subject": subject,
                    "status": "sent"
                }
            }))
        else:
            print(json.dumps({
                "ok": False,
                "error": f"Email failed: {result.get('response', 'Unknown error')}",
                "speech": f"Failed to send email to {display_name}"
            }))
            sys.exit(1)
        
    except ValueError as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": str(e)
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Error sending email: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

