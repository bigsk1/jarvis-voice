#!/usr/bin/env python3
"""
Process/Service Monitor - Python Example
Monitor systemd services or processes, alert when down, auto-resolve when back up

Features:
- Monitors systemd services OR processes by name
- Sends alert when service stops
- Auto-resolves when service comes back up
- Works for any service (nginx, postgresql, ollama, etc.)
"""
import subprocess
import requests
import time
import sys
import re

# Configuration
JARVIS_API = "http://localhost:8880/api/alerts"
SOURCE_NAME = "process-monitor"
CHECK_INTERVAL = 60  # seconds

# Services to monitor (systemd services)
SERVICES_TO_MONITOR = [
    "nginx",
    "postgresql",
    # "ollama",  # Add your services here
]

# Processes to monitor (by name)
PROCESSES_TO_MONITOR = [
    # "python.*server.py",  # Regex pattern
    # "node.*app.js",
]

def check_service(service_name):
    """Check if systemd service is active"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False

def check_process(process_pattern):
    """Check if process is running (regex match)"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", process_pattern],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0  # 0 = found, 1 = not found
    except Exception:
        return False

def send_alert(title, description, severity):
    """Send alert to Jarvis"""
    try:
        response = requests.post(
            JARVIS_API,
            json={
                "title": title,
                "description": description,
                "severity": severity,
                "source": SOURCE_NAME
            },
            timeout=10
        )
        return response.json() if response.ok else None
    except Exception as e:
        print(f"❌ Failed to send alert: {e}", file=sys.stderr)
        return None

def resolve_alert_by_title(title_pattern):
    """Resolve pending alert matching title pattern"""
    try:
        # Get pending alerts
        response = requests.get(
            JARVIS_API,
            params={"status": "pending", "source": SOURCE_NAME},
            timeout=10
        )
        if not response.ok:
            return False
        
        alerts = response.json().get('alerts', [])
        
        # Find and resolve matching alert
        for alert in alerts:
            if title_pattern in alert.get('title', ''):
                alert_id = alert['id']
                resolve_url = JARVIS_API.replace('/alerts', f'/alerts/{alert_id}/resolve')
                requests.post(resolve_url, timeout=10)
                return True
        
        return False
    except Exception as e:
        print(f"⚠️  Failed to resolve alert: {e}", file=sys.stderr)
        return False

def main():
    """Main monitoring loop"""
    print("🔍 Process/Service Monitor")
    print(f"   Jarvis API: {JARVIS_API}")
    print(f"   Check interval: {CHECK_INTERVAL}s")
    print(f"   Monitoring services: {SERVICES_TO_MONITOR}")
    print(f"   Monitoring processes: {PROCESSES_TO_MONITOR}")
    print()
    
    last_status = {}
    
    while True:
        current_time = time.strftime('%H:%M:%S')
        
        # Check systemd services
        for service in SERVICES_TO_MONITOR:
            is_active = check_service(service)
            prev = last_status.get(f"service:{service}")
            
            # Service stopped
            if prev and not is_active:
                print(f"[{current_time}] ❌ SERVICE STOPPED: {service}")
                result = send_alert(
                    f"Service Stopped: {service}",
                    f"Systemd service '{service}' is no longer active",
                    "high"
                )
                if result and result.get("ok"):
                    print(f"           ✅ Alert sent (ID: {result.get('alert_id')})")
            
            # Service started
            elif prev == False and is_active:
                print(f"[{current_time}] ✅ SERVICE ACTIVE: {service}")
                if resolve_alert_by_title(f"Service Stopped: {service}"):
                    print(f"           ✅ Resolved alert in Jarvis")
            
            last_status[f"service:{service}"] = is_active
        
        # Check processes
        for process in PROCESSES_TO_MONITOR:
            is_running = check_process(process)
            prev = last_status.get(f"process:{process}")
            
            # Process stopped
            if prev and not is_running:
                print(f"[{current_time}] ❌ PROCESS STOPPED: {process}")
                result = send_alert(
                    f"Process Stopped: {process}",
                    f"Process matching '{process}' is no longer running",
                    "high"
                )
                if result and result.get("ok"):
                    print(f"           ✅ Alert sent (ID: {result.get('alert_id')})")
            
            # Process started
            elif prev == False and is_running:
                print(f"[{current_time}] ✅ PROCESS RUNNING: {process}")
                if resolve_alert_by_title(f"Process Stopped: {process}"):
                    print(f"           ✅ Resolved alert in Jarvis")
            
            last_status[f"process:{process}"] = is_running
        
        # Print status summary periodically
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n✋ Monitoring stopped")
        sys.exit(0)

