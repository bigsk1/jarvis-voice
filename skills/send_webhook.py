#!/usr/bin/env python3
"""
Jarvis Skill: Send Webhook
Sends POST requests to webhooks for triggering external services.
"""
import sys
import json
import requests


def main():
    """Send webhook POST request."""
    # Read input from command line argument
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    
    # Extract parameters
    url = input_data.get("url")
    data = input_data.get("data", {})
    headers = input_data.get("headers", {"Content-Type": "application/json"})
    
    if not url:
        return_error("URL is required")
        return 1
    
    # Ensure Content-Type is set
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    
    # Send webhook
    try:
        response = requests.post(
            url,
            json=data,
            headers=headers,
            timeout=10
        )
        
        # Check response
        if response.status_code >= 200 and response.status_code < 300:
            return_success(
                speech=f"Webhook sent successfully to {url}. Status: {response.status_code}",
                data={
                    "url": url,
                    "status_code": response.status_code,
                    "response": response.text[:200]  # First 200 chars
                }
            )
            return 0
        else:
            return_error(
                speech=f"Webhook failed with status {response.status_code}",
                data={
                    "url": url,
                    "status_code": response.status_code,
                    "error": response.text[:200]
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
    sys.exit(main())

