#!/usr/bin/env python3
"""
Docker Container Monitor - Python Example
Monitor Docker containers and alert Jarvis if they stop
Requires: pip install docker requests
"""
import docker
import requests
import time
import sys

# Configuration
JARVIS_API = "http://localhost:8880/api/alerts"
CONTAINERS_TO_MONITOR = [
    "kokoro-tts",
    "comfyui",
    "ollama"
]
CHECK_INTERVAL = 60  # seconds

def send_alert(title, description, severity, metadata=None):
    """Send alert to Jarvis."""
    payload = {
        "title": title,
        "description": description,
        "severity": severity,
        "source": "docker-monitor",
        "metadata": metadata
    }
    
    try:
        response = requests.post(JARVIS_API, json=payload, timeout=10)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send alert: {e}", file=sys.stderr)
        return None

def check_container(client, container_name):
    """Check if container is running."""
    try:
        container = client.containers.get(container_name)
        return container.status == "running"
    except docker.errors.NotFound:
        return False
    except Exception as e:
        print(f"Error checking {container_name}: {e}", file=sys.stderr)
        return None

def main():
    """Main monitoring loop."""
    print("🐳 Docker Container Monitor")
    print(f"   Monitoring: {', '.join(CONTAINERS_TO_MONITOR)}")
    print(f"   Check interval: {CHECK_INTERVAL}s")
    print(f"   Jarvis API: {JARVIS_API}")
    print()
    
    # Initialize Docker client
    try:
        client = docker.from_env()
    except Exception as e:
        print(f"❌ Failed to connect to Docker: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Track last known status
    last_status = {}
    
    while True:
        for container_name in CONTAINERS_TO_MONITOR:
            is_running = check_container(client, container_name)
            
            if is_running is None:
                continue  # Error checking, skip this iteration
            
            prev_status = last_status.get(container_name)
            
            # Status changed from running to stopped
            if prev_status and not is_running:
                print(f"❌ {container_name} stopped - Sending alert")
                result = send_alert(
                    title=f"Docker Container Stopped",
                    description=f"Container '{container_name}' is no longer running",
                    severity="high",
                    metadata={
                        "container": container_name,
                        "host": "proxmox-gpu-vm"
                    }
                )
                if result and result.get("ok"):
                    print(f"✅ Alert sent (ID: {result.get('alert_id')})")
            
            # Status changed from stopped to running
            elif prev_status == False and is_running:
                print(f"✅ {container_name} started")
            
            # Update status
            last_status[container_name] = is_running
        
        # Print status
        statuses = []
        for name in CONTAINERS_TO_MONITOR:
            status = last_status.get(name)
            if status:
                statuses.append(f"{name}:✓")
            elif status is False:
                statuses.append(f"{name}:✗")
            else:
                statuses.append(f"{name}:?")
        
        print(f"Status: {' '.join(statuses)}", end="\r")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n✋ Monitoring stopped")
        sys.exit(0)

