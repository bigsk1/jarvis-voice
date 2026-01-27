#!/usr/bin/env python3
"""
Samantha Tool - Talk to Samantha AI assistant on remote VPS2

Samantha is a SEPARATE AI assistant running on a cloud VPS (vps2).
She is NOT part of Jarvis's local network and has NO access to:
- Jarvis's tools (prices, weather, memory, local TTS, etc.)
- Home automation or local network devices
- Fred or any local systems

Think of her as a remote colleague you can ask for help.
She does have access to Jarvis API and can send POST requests as needed.
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
TIMEOUT_SECONDS = 120  # Samantha may need time for complex tasks

# For reference - Samantha's capabilities (she has different tools than Jarvis)
# Discord/Telegram posting, browser automation, cron scheduling, file ops on VPS2
# She does NOT have: local TTS, price APIs, memory DB, home automation, local network


def call_samantha(message: str, session: str = "jarvis") -> dict:
    """
    Send a message to Samantha and get her response.
    
    Args:
        message: The message/task for Samantha
        session: Session ID for conversation context (default: 'jarvis')
    
    Returns:
        dict with 'ok', 'response', 'speech' keys
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
    
    payload = {
        "model": "clawdbot:main",
        "messages": [
            {"role": "user", "content": message}
        ],
        "user": session,  # Persistent session for multi-turn
        "stream": False   # Explicit non-streaming for cleaner response
    }
    
    try:
        response = requests.post(
            SAMANTHA_URL,
            headers=headers,
            json=payload,
            timeout=TIMEOUT_SECONDS
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
                    "usage": data.get("usage", {}),  # Token usage if available
                    "note": "Response from remote VPS2 - Samantha has no access to Jarvis's local tools"
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
                "error": "Samantha is not available - Clawdbot may be stopped or Tailscale serve not running",
                "status_code": response.status_code,
                "hint": "Try: SSH to vps2 and check tailscale serve status"
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
            "error": f"Samantha timed out after {TIMEOUT_SECONDS} seconds - task may be too complex",
            "hint": "For long tasks, consider using the webhook instead"
        }
    
    except requests.exceptions.ConnectionError as e:
        return {
            "ok": False,
            "error": "Cannot connect to Samantha - VPS2 may be down or Tailscale not connected",
            "details": str(e)[:200],
            "hint": "Check if VPS2 is reachable via Tailscale"
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
    
    if not message:
        print(json.dumps({
            "ok": False,
            "error": "message is required"
        }))
        sys.exit(1)
    
    result = call_samantha(message, session)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
