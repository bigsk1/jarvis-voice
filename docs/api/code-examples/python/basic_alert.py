#!/usr/bin/env python3
"""
Basic Jarvis Alert - Python Example
Send a simple alert to Jarvis API
"""
import requests

# Jarvis API endpoint
JARVIS_API = "http://localhost:8880/api/alerts"

def send_alert(title, description, severity="medium", source="python-app"):
    """Send alert to Jarvis."""
    payload = {
        "title": title,
        "description": description,
        "severity": severity,
        "source": source
    }
    
    try:
        response = requests.post(JARVIS_API, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send alert: {e}")
        return None

if __name__ == "__main__":
    # Example usage
    result = send_alert(
        title="Test Alert from Python",
        description="This is a test alert",
        severity="medium"
    )
    
    if result and result.get("ok"):
        print(f"✅ Alert sent successfully! ID: {result.get('alert_id')}")
    else:
        print("❌ Failed to send alert")

