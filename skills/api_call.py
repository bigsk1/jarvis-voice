#!/usr/bin/env python3
"""
Jarvis Skill: API Call
Makes HTTP API calls to REST endpoints.
"""
import sys
import json
import requests


def main():
    """Make API call."""
    # Read input from command line argument
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    
    # Extract parameters
    url = input_data.get("url")
    method = input_data.get("method", "GET").upper()
    headers = input_data.get("headers", {})
    body = input_data.get("body", None)
    params = input_data.get("params", None)
    
    if not url:
        return_error("URL is required")
        return 1
    
    if method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
        return_error(f"Invalid HTTP method: {method}")
        return 1
    
    # Make API call
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=body if body else None,
            params=params,
            timeout=15
        )
        
        # Try to parse JSON response
        try:
            response_data = response.json()
        except:
            response_data = {"raw": response.text[:500]}
        
        # Check response
        if response.status_code >= 200 and response.status_code < 300:
            # Success
            speech = f"API call succeeded with status {response.status_code}."
            
            # Add some context about the response
            if isinstance(response_data, dict):
                keys = list(response_data.keys())[:3]
                if keys:
                    speech += f" Response contains: {', '.join(keys)}"
            
            return_success(
                speech=speech,
                data={
                    "url": url,
                    "method": method,
                    "status_code": response.status_code,
                    "response": response_data
                }
            )
            return 0
        else:
            # HTTP error
            speech = f"API call returned status {response.status_code}."
            return_error(
                speech=speech,
                data={
                    "url": url,
                    "method": method,
                    "status_code": response.status_code,
                    "response": response_data
                }
            )
            return 1
            
    except requests.Timeout:
        return_error("API request timed out")
        return 1
    except requests.RequestException as e:
        return_error(f"API request failed: {str(e)}")
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

