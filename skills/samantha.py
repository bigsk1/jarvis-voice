#!/usr/bin/env python3
"""
Samantha Tool - Talk to a separately hosted AI assistant

Samantha is a separate AI assistant running on a remote host. Her access to
Jarvis APIs and other systems depends on credentials and tools configured on
that host; do not treat her as an isolated security boundary.

Think of her as a remote colleague you can ask for help.
This installation may give her Jarvis API access for assigned work.
Only use when the user EXPLICITLY requests Samantha by name.

Endpoint: SAMANTHA_URL env var
Auth: SAMANTHA_GATEWAY_TOKEN env var
"""

import sys
import json
import os
import requests

# Configuration - loaded from environment (no hardcoded URLs/tokens)
SAMANTHA_URL = os.environ.get("SAMANTHA_URL", "https://your-vps.ts.net/v1/chat/completions")
SAMANTHA_TOKEN = os.environ.get("SAMANTHA_GATEWAY_TOKEN", "")
SAMANTHA_MODEL = os.environ.get("SAMANTHA_MODEL", "openclaw/main")
DEFAULT_TIMEOUT = 120  # Default timeout, can be overridden per-call (30-300s)

# For reference - Samantha's capabilities (she has different tools than Jarvis)
# The remote deployment may have messaging, browser, scheduling, or file tools.
# Her Jarvis API access depends on the remote deployment configuration.


def call_samantha(message: str, session: str = "jarvis", priority: str = "normal", timeout: int = 120) -> dict:
    """
    Send a message to Samantha and get her response.
    
    Args:
        message: The message/task for Samantha
        session: Session ID for conversation context. Use 'jarvis' (default) to continue
                 previous conversations - Samantha remembers prior context. Use a unique
                 ID like 'jarvis-research-jan26' for isolated tasks that shouldn't affect
                 main conversation history. Same session = context retained.
        priority: Task priority - 'urgent', 'normal', or 'background'
        timeout: Request timeout in seconds (default: 120)
    
    Returns:
        dict with 'ok', 'response', 'speech', 'priority' keys
    """
    if not SAMANTHA_TOKEN:
        return {
            "ok": False,
            "error": "SAMANTHA_GATEWAY_TOKEN not configured in environment",
            "hint": "Add SAMANTHA_GATEWAY_TOKEN to cloud.env or local.env"
        }
    
    if "your-vps" in SAMANTHA_URL:
        return {
            "ok": False,
            "error": "SAMANTHA_URL not configured in environment",
            "hint": "Add SAMANTHA_URL to cloud.env or local.env"
        }
    
    headers = {
        "Authorization": f"Bearer {SAMANTHA_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Prepend priority hint to message if urgent (helps Samantha prioritize)
    if priority == "urgent":
        task_message = f"[URGENT - Jarvis needs this immediately] {message}"
    elif priority == "background":
        task_message = f"[Background task - low priority] {message}"
    else:
        task_message = message
    
    payload = {
        "model": SAMANTHA_MODEL,
        "messages": [
            {"role": "user", "content": task_message}
        ],
        "user": session,  # Persistent session for multi-turn
        "stream": False   # Explicit non-streaming for cleaner response
    }
    
    try:
        response = requests.post(
            SAMANTHA_URL,
            headers=headers,
            json=payload,
            timeout=timeout  # Use caller-specified timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract response from OpenAI format
            if "choices" in data and len(data["choices"]) > 0:
                assistant_message = data["choices"][0].get("message", {})
                content = assistant_message.get("content", "")
                
                # Smart truncation - preserve complete sentences for speech
                if len(content) > 500:
                    truncated = content[:500]
                    # Try to end at a sentence boundary
                    last_period = truncated.rfind('. ')
                    if last_period > 200:  # Only if we have reasonable content
                        speech = truncated[:last_period + 1] + " ..."
                    else:
                        speech = truncated + "..."
                else:
                    speech = content
                
                return {
                    "ok": True,
                    "response": content,
                    "speech": f"Samantha says: {speech}",
                    "model": data.get("model", "unknown"),
                    "session": session,
                    "priority": priority,
                    "usage": data.get("usage", {}),  # Token usage if available
                    "data": {
                        "response": content,
                        "model": data.get("model", "unknown"),
                        "session": session,
                        "priority": priority,
                        "usage": data.get("usage", {}),
                    },
                    "note": "Response from a separate remote assistant; its Jarvis API access depends on deployment credentials"
                }
            else:
                return {
                    "ok": False,
                    "error": "No response from Samantha",
                    "raw": data
                }
        
        elif response.status_code == 401:
            return {
                "ok": False,
                "error": "Authentication failed - check SAMANTHA_GATEWAY_TOKEN",
                "status_code": response.status_code
            }
        
        elif response.status_code == 502 or response.status_code == 503:
            return {
                "ok": False,
                "error": "Samantha is not available - the remote service or private route may be down",
                "status_code": response.status_code,
                "hint": "Check the configured remote service and private HTTPS route"
            }
        
        else:
            return {
                "ok": False,
                "error": f"Samantha returned status {response.status_code}",
                "status_code": response.status_code,
                "body": response.text[:500]
            }
    
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error": f"Samantha timed out after {timeout} seconds - task may be too complex",
            "hint": "Try increasing timeout (up to 300s) or use webhook for very long tasks"
        }
    
    except requests.exceptions.ConnectionError as e:
        return {
            "ok": False,
            "error": "Cannot connect to Samantha - the remote host or route may be down",
            "details": str(e)[:200],
            "hint": "Check that the configured remote host is reachable"
        }
    
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to contact Samantha: {str(e)}"
        }


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Usage: samantha.py '{\"message\": \"your message\"}'"
        }))
        sys.exit(1)
    
    try:
        args = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({
            "ok": False,
            "error": f"Invalid JSON: {e}"
        }))
        sys.exit(1)
    
    message = args.get("message", "")
    session = args.get("session", "jarvis")
    priority = args.get("priority", "normal")
    timeout = args.get("timeout", 120)
    
    if not message:
        print(json.dumps({
            "ok": False,
            "error": "message is required"
        }))
        sys.exit(1)
    
    # Validate priority
    if priority not in ["urgent", "normal", "background"]:
        priority = "normal"
    
    # Validate timeout (30-300 seconds)
    timeout = max(30, min(300, int(timeout)))
    
    result = call_samantha(message, session, priority, timeout)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
