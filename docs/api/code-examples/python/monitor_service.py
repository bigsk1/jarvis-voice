#!/usr/bin/env python3
"""
Service Monitor - Python Example
Monitor a service/URL and send alerts to Jarvis if down
"""
import requests
import time
import sys

# Configuration
JARVIS_API = "http://localhost:8880/api/alerts"
SERVICE_NAME = "ComfyUI"
SERVICE_URL = "http://192.168.70.100:8188/health"
CHECK_INTERVAL = 60  # seconds

def check_service():
    """Check if service is responding."""
    try:
        response = requests.get(SERVICE_URL, timeout=10)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def send_alert(title, description, severity, auto_resolve_url=None):
    """Send alert to Jarvis."""
    payload = {
        "title": title,
        "description": description,
        "severity": severity,
        "source": "service-monitor",
        "auto_resolve_url": auto_resolve_url,
        "auto_resolve_check_interval": 300  # Check every 5 minutes
    }
    
    try:
        response = requests.post(JARVIS_API, json=payload, timeout=10)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send alert: {e}", file=sys.stderr)
        return None

def main():
    """Main monitoring loop."""
    print(f"🔍 Monitoring {SERVICE_NAME} at {SERVICE_URL}")
    print(f"   Check interval: {CHECK_INTERVAL}s")
    print(f"   Jarvis API: {JARVIS_API}")
    print()
    
    last_status = None
    
    while True:
        is_up = check_service()
        
        # Status changed from up to down
        if last_status and not is_up:
            print(f"❌ {SERVICE_NAME} is DOWN - Sending alert to Jarvis")
            result = send_alert(
                title=f"{SERVICE_NAME} Down",
                description=f"{SERVICE_NAME} at {SERVICE_URL} is not responding",
                severity="high",
                auto_resolve_url=SERVICE_URL  # Enable auto-healing
            )
            if result and result.get("ok"):
                print(f"✅ Alert sent (ID: {result.get('alert_id')})")
        
        # Status changed from down to up
        elif last_status == False and is_up:
            print(f"✅ {SERVICE_NAME} is back UP")
        
        # Status unchanged
        elif is_up:
            print(f"✓ {SERVICE_NAME} is UP", end="\r")
        
        last_status = is_up
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n✋ Monitoring stopped")
        sys.exit(0)

