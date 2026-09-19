#!/usr/bin/env python3
"""
OpenClaw tool — talk to a separately hosted OpenClaw gateway.

The remote agent has its own tools and context. Its access to Jarvis APIs
depends on credentials configured on that host; do not treat it as an isolated
security boundary. Only use when the user explicitly asks for OpenClaw.

Endpoint: OPENCLAW_URL
Auth: OPENCLAW_GATEWAY_TOKEN
"""

import json
import os
import sys

import requests

DEFAULT_URL = "https://your-vps.ts.net/v1/chat/completions"
DEFAULT_TIMEOUT = 120


OPENCLAW_URL = os.environ.get("OPENCLAW_URL") or DEFAULT_URL
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
OPENCLAW_MODEL = os.environ.get("OPENCLAW_MODEL") or "openclaw/main"


def call_openclaw(message: str, session: str = "jarvis", priority: str = "normal", timeout: int = 120) -> dict:
    """Send a message to the remote OpenClaw gateway and return its response."""
    if not OPENCLAW_TOKEN:
        return {
            "ok": False,
            "error": "OPENCLAW_GATEWAY_TOKEN not configured in environment",
            "hint": "Add OPENCLAW_GATEWAY_TOKEN to cloud.env or local.env",
        }

    if "your-vps" in OPENCLAW_URL:
        return {
            "ok": False,
            "error": "OPENCLAW_URL not configured in environment",
            "hint": "Add OPENCLAW_URL to cloud.env or local.env",
        }

    headers = {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
    }

    if priority == "urgent":
        task_message = f"[URGENT - Jarvis needs this immediately] {message}"
    elif priority == "background":
        task_message = f"[Background task - low priority] {message}"
    else:
        task_message = message

    payload = {
        "model": OPENCLAW_MODEL,
        "messages": [
            {"role": "user", "content": task_message}
        ],
        "user": session,
        "stream": False,
    }

    try:
        response = requests.post(
            OPENCLAW_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

        if response.status_code == 200:
            data = response.json()

            if "choices" in data and len(data["choices"]) > 0:
                assistant_message = data["choices"][0].get("message", {})
                content = assistant_message.get("content", "")

                if len(content) > 500:
                    truncated = content[:500]
                    last_period = truncated.rfind(". ")
                    if last_period > 200:
                        speech = truncated[: last_period + 1] + " ..."
                    else:
                        speech = truncated + "..."
                else:
                    speech = content

                return {
                    "ok": True,
                    "response": content,
                    "speech": f"OpenClaw says: {speech}",
                    "model": data.get("model", "unknown"),
                    "session": session,
                    "priority": priority,
                    "usage": data.get("usage", {}),
                    "data": {
                        "response": content,
                        "model": data.get("model", "unknown"),
                        "session": session,
                        "priority": priority,
                        "usage": data.get("usage", {}),
                    },
                    "note": "Response from a separate remote OpenClaw agent; its Jarvis API access depends on deployment credentials",
                }

            return {
                "ok": False,
                "error": "No response from OpenClaw",
                "raw": data,
            }

        if response.status_code == 401:
            return {
                "ok": False,
                "error": "Authentication failed - check OPENCLAW_GATEWAY_TOKEN",
                "status_code": response.status_code,
            }

        if response.status_code in {502, 503}:
            return {
                "ok": False,
                "error": "OpenClaw is not available - the remote service or private route may be down",
                "status_code": response.status_code,
                "hint": "Check the configured remote service and private HTTPS route",
            }

        return {
            "ok": False,
            "error": f"OpenClaw returned status {response.status_code}",
            "status_code": response.status_code,
            "body": response.text[:500],
        }

    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error": f"OpenClaw timed out after {timeout} seconds - task may be too complex",
            "hint": "Try increasing timeout (up to 300s) or use webhook for very long tasks",
        }

    except requests.exceptions.ConnectionError as e:
        return {
            "ok": False,
            "error": "Cannot connect to OpenClaw - the remote host or route may be down",
            "details": str(e)[:200],
            "hint": "Check that the configured remote host is reachable",
        }

    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to contact OpenClaw: {str(e)}",
        }


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Usage: openclaw.py '{\"message\": \"your message\"}'",
        }))
        sys.exit(1)

    try:
        args = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({
            "ok": False,
            "error": f"Invalid JSON: {e}",
        }))
        sys.exit(1)

    message = args.get("message", "")
    session = args.get("session", "jarvis")
    priority = args.get("priority", "normal")
    timeout = args.get("timeout", 120)

    if not message:
        print(json.dumps({
            "ok": False,
            "error": "message is required",
        }))
        sys.exit(1)

    if priority not in ["urgent", "normal", "background"]:
        priority = "normal"

    timeout = max(30, min(300, int(timeout)))

    result = call_openclaw(message, session, priority, timeout)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
