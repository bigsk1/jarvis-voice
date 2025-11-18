#!/usr/bin/env python3
"""
Jarvis Monitoring Agent (Docker)
Universal monitoring agent for remote servers

Monitors:
- Docker containers
- HTTP/HTTPS endpoints
- System resources (TODO: future enhancement)

Sends alerts to Jarvis API when issues detected.
"""
import os
import requests
import docker
import time
import sys
import signal
from datetime import datetime

# Configuration from environment variables
JARVIS_API = os.getenv("JARVIS_API", "http://localhost:8880/api/alerts")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
MONITOR_CONTAINERS = [c.strip() for c in os.getenv("MONITOR_CONTAINERS", "").split(",") if c.strip()]
MONITOR_URLS = [u.strip() for u in os.getenv("MONITOR_URLS", "").split(",") if u.strip()]
SOURCE_NAME = os.getenv("SOURCE_NAME", os.uname().nodename)
AUTO_RESOLVE_INTERVAL = int(os.getenv("AUTO_RESOLVE_INTERVAL", "60"))  # Faster auto-resolve (60s default)

# Global state
running = True


def signal_handler(sig, frame):
    """Handle graceful shutdown."""
    global running
    print("\n🛑 Shutdown signal received, stopping gracefully...")
    running = False


def send_alert(title, description, severity, auto_resolve_url=None, metadata=None):
    """Send alert to Jarvis."""
    payload = {
        "title": title,
        "description": description,
        "severity": severity,
        "source": SOURCE_NAME,
    }
    
    if auto_resolve_url:
        payload["auto_resolve_url"] = auto_resolve_url
        payload["auto_resolve_check_interval"] = AUTO_RESOLVE_INTERVAL  # Use configured interval
    
    if metadata:
        payload["metadata"] = metadata
    
    try:
        response = requests.post(JARVIS_API, json=payload, timeout=10)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to send alert: {e}", file=sys.stderr)
        return None


def resolve_alerts_by_source(title_pattern: str):
    """Resolve pending alerts matching title pattern from this source."""
    try:
        # Get pending alerts for this source
        response = requests.get(
            JARVIS_API.replace('/alerts', '/alerts'),
            params={"status": "pending", "source": SOURCE_NAME},
            timeout=10
        )
        if not response.ok:
            return False
        
        alerts = response.json().get('alerts', [])
        
        # Find alerts matching the pattern
        for alert in alerts:
            if title_pattern in alert.get('title', ''):
                alert_id = alert['id']
                # Resolve this alert
                resolve_url = JARVIS_API.replace('/alerts', f'/alerts/{alert_id}/resolve')
                requests.post(resolve_url, timeout=10)
                return True
        
        return False
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Failed to resolve alerts: {e}", file=sys.stderr)
        return False


def check_url(url):
    """Check if URL is responding."""
    try:
        response = requests.get(url, timeout=10, allow_redirects=True)
        return 200 <= response.status_code < 400
    except requests.exceptions.RequestException:
        return False


def check_container(client, name):
    """Check if Docker container is running."""
    try:
        container = client.containers.get(name)
        return container.status == "running", container.status
    except docker.errors.NotFound:
        return False, "not_found"
    except docker.errors.APIError as e:
        print(f"⚠️  Docker API error for {name}: {e}", file=sys.stderr)
        return None, "error"


def main():
    """Main monitoring loop."""
    print("=" * 60)
    print("🔍 Jarvis Monitoring Agent")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Jarvis API: {JARVIS_API}")
    print(f"Source Name: {SOURCE_NAME}")
    print(f"Check Interval: {CHECK_INTERVAL}s")
    
    if MONITOR_CONTAINERS:
        print(f"Monitoring Containers: {', '.join(MONITOR_CONTAINERS)}")
    if MONITOR_URLS:
        print(f"Monitoring URLs: {', '.join(MONITOR_URLS)}")
    
    print("=" * 60)
    print()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize Docker client
    docker_client = None
    if MONITOR_CONTAINERS:
        try:
            docker_client = docker.from_env()
            print("✅ Docker client initialized")
        except Exception as e:
            print(f"⚠️  Docker not available: {e}")
            print("   Container monitoring disabled")
    
    # Write health file for Docker health check
    try:
        with open('/tmp/monitor_healthy', 'w') as f:
            f.write('ok')
    except:
        pass  # Ignore if can't write (non-Docker environment)
    
    print(f"✅ {SOURCE_NAME} monitoring started")
    print()
    
    # Track last known status
    last_status = {}
    check_count = 0
    
    while running:
        check_count += 1
        current_time = datetime.now().strftime('%H:%M:%S')
        
        # Check URLs
        for url in MONITOR_URLS:
            is_up = check_url(url)
            prev = last_status.get(f"url:{url}")
            
            # Status changed from up to down
            if prev and not is_up:
                print(f"[{current_time}] ❌ URL DOWN: {url}")
                result = send_alert(
                    f"Service Down: {url}",
                    f"URL {url} is not responding",
                    "high",
                    auto_resolve_url=url,
                    metadata={"url": url, "source": SOURCE_NAME}
                )
                if result and result.get("ok"):
                    print(f"           ✅ Alert sent (ID: {result.get('alert_id')})")
            
            # Status changed from down to up
            elif prev == False and is_up:
                print(f"[{current_time}] ✅ URL UP: {url}")
            
            last_status[f"url:{url}"] = is_up
        
        # Check Docker containers
        if docker_client:
            for container_name in MONITOR_CONTAINERS:
                is_running, status = check_container(docker_client, container_name)
                prev = last_status.get(f"container:{container_name}")
                
                # Status changed from running to stopped
                if prev and not is_running:
                    print(f"[{current_time}] ❌ CONTAINER STOPPED: {container_name} (status: {status})")
                    result = send_alert(
                        f"Container Stopped: {container_name}",
                        f"Docker container '{container_name}' is no longer running (status: {status})",
                        "high",
                        metadata={
                            "container": container_name,
                            "status": status,
                            "host": SOURCE_NAME
                        }
                    )
                    if result and result.get("ok"):
                        print(f"           ✅ Alert sent (ID: {result.get('alert_id')})")
                
                # Status changed from stopped to running
                elif prev == False and is_running:
                    print(f"[{current_time}] ✅ CONTAINER RUNNING: {container_name}")
                    # Resolve any pending alerts for this container
                    if resolve_alerts_by_source(f"Container Stopped: {container_name}"):
                        print(f"           ✅ Resolved alert in Jarvis")
                
                last_status[f"container:{container_name}"] = is_running
        
        # Print status summary (only every 10 checks to reduce noise)
        if check_count % 10 == 0:
            statuses = []
            
            for url in MONITOR_URLS:
                status = last_status.get(f"url:{url}")
                if status:
                    statuses.append(f"URL({url.split('//')[-1].split('/')[0]}):✓")
                elif status is False:
                    statuses.append(f"URL({url.split('//')[-1].split('/')[0]}):✗")
            
            for container_name in MONITOR_CONTAINERS:
                status = last_status.get(f"container:{container_name}")
                if status:
                    statuses.append(f"{container_name}:✓")
                elif status is False:
                    statuses.append(f"{container_name}:✗")
            
            if statuses:
                print(f"[{current_time}] Status: {' | '.join(statuses)}")
        
        # Update health file
        try:
            with open('/tmp/monitor_healthy', 'w') as f:
                f.write(datetime.now().isoformat())
        except:
            pass
        
        # Wait before next check
        time.sleep(CHECK_INTERVAL)
    
    print("\n✅ Monitoring agent stopped gracefully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)

