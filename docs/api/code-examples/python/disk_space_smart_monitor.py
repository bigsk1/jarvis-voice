#!/usr/bin/env python3
"""
Smart Disk Space Monitor - Python Example
Monitor disk space and auto-resolve when space is freed

Features:
- Alerts when disk usage exceeds threshold
- Auto-resolves when disk space drops below threshold
- No spam - only alerts on state change
"""
import subprocess
import requests
import time
import sys
import re

# Configuration
JARVIS_API = "http://localhost:8880/api/alerts"
SOURCE_NAME = "disk-monitor"
CHECK_INTERVAL = 300  # 5 minutes
THRESHOLD_ALERT = 90  # Alert when usage > 90%
THRESHOLD_RESOLVE = 85  # Resolve when usage < 85%

# Partitions to monitor
PARTITIONS = [
    "/",
    "/home",
    # "/mnt/data",
]

def get_disk_usage(partition):
    """Get disk usage percentage for partition"""
    try:
        result = subprocess.run(
            ["df", "-h", partition],
            capture_output=True,
            text=True,
            timeout=5
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            # Parse percentage from output
            match = re.search(r'(\d+)%', lines[1])
            if match:
                return int(match.group(1))
        return None
    except Exception as e:
        print(f"⚠️  Error checking {partition}: {e}", file=sys.stderr)
        return None

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
        response = requests.get(
            JARVIS_API,
            params={"status": "pending", "source": SOURCE_NAME},
            timeout=10
        )
        if not response.ok:
            return False
        
        alerts = response.json().get('alerts', [])
        
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
    print("💾 Smart Disk Space Monitor")
    print(f"   Jarvis API: {JARVIS_API}")
    print(f"   Check interval: {CHECK_INTERVAL}s")
    print(f"   Alert threshold: {THRESHOLD_ALERT}%")
    print(f"   Resolve threshold: {THRESHOLD_RESOLVE}%")
    print(f"   Monitoring: {PARTITIONS}")
    print()
    
    alert_active = {}  # Track if alert is active for each partition
    
    while True:
        current_time = time.strftime('%H:%M:%S')
        
        for partition in PARTITIONS:
            usage = get_disk_usage(partition)
            
            if usage is None:
                continue
            
            is_alert = alert_active.get(partition, False)
            
            # Usage exceeds threshold and no active alert
            if usage >= THRESHOLD_ALERT and not is_alert:
                print(f"[{current_time}] ❌ DISK SPACE LOW: {partition} at {usage}%")
                result = send_alert(
                    f"Disk Space Low: {partition}",
                    f"Partition {partition} is at {usage}% capacity (threshold: {THRESHOLD_ALERT}%)",
                    "high"
                )
                if result and result.get("ok"):
                    print(f"           ✅ Alert sent (ID: {result.get('alert_id')})")
                    alert_active[partition] = True
            
            # Usage dropped below resolve threshold and alert is active
            elif usage < THRESHOLD_RESOLVE and is_alert:
                print(f"[{current_time}] ✅ DISK SPACE OK: {partition} at {usage}%")
                if resolve_alert_by_title(f"Disk Space Low: {partition}"):
                    print(f"           ✅ Resolved alert in Jarvis")
                    alert_active[partition] = False
            
            # Status unchanged - just log
            elif usage >= THRESHOLD_ALERT:
                print(f"[{current_time}] ⚠️  {partition}: {usage}% (still high)", end='\r')
            else:
                print(f"[{current_time}] ✓  {partition}: {usage}% (OK)", end='\r')
        
        print()  # Newline after status updates
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n✋ Monitoring stopped")
        sys.exit(0)

