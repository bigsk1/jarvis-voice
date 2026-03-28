#!/usr/bin/env python3
"""
Self-Healing Daemon
Periodically checks alerts with auto_resolve_url and monitors systemd services.
Auto-resolves if URL returns 2xx/3xx status codes.
Alerts and attempts restart if monitored services go down.

Check intervals:
- Per-alert custom interval (default: 300 seconds / 5 minutes)
- Global check loop: 60 seconds
- Service grace period: 90 seconds (avoids false alarms during reboots)
"""

import sys
import os
import time
import sqlite3
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB
from service_logger import ServiceLogger


# Maximum tool calls per check (safety limit)
MAX_CHECKS_PER_LOOP = 10

# Systemd service monitoring configuration
# Format: {"service_name": {"required": bool, "restart": bool}}
# - required: If True, service must exist. If False, skip if not installed.
# - restart: If True, attempt automatic restart when down.
MONITORED_SYSTEMD_SERVICES = {
    "unifi-protect-webhook": {"required": False, "restart": False}, # Optional - may not be installed - this is already running as a systemd service with its own restart logic
    "opencode-jarvis": {"required": False, "restart": False},  # Optional - may not be installed - this is already running as a systemd service with its own restart logic
}

# Sibling daemon monitoring (via PID files)
# These run alongside self_healing_daemon via bin/jarvis-services
# Format: {"name": {"pid_file": "relative/path.pid", "script": "script_name.py", "restart": bool}}
MONITORED_DAEMONS = {
    "reminder_scheduler": {
        "pid_file": "logs/reminder_scheduler.pid",
        "script": "reminder_scheduler.py",
        "restart": True,
    },
    "follow_up_daemon": {
        "pid_file": "logs/follow_up_daemon.pid",
        "script": "follow_up_daemon.py",
        "restart": True,
    },
    "jarvis_api": {
        "pid_file": "logs/jarvis-api.pid",
        "script": "server.py",  # API runs as python3 server.py
        "restart": False,  # DO NOT auto-restart - just notify
        "notify_only": True,  # Custom flag: only speak, don't try to restart
    },
    # Note: Don't monitor self_healing_daemon - that's us!
}

# Grace period before alerting (seconds) - avoids false alarms during reboots
SERVICE_GRACE_PERIOD = 90
DAEMON_GRACE_PERIOD = 60  # Shorter for local daemons


def retry_on_db_lock(func, max_retries=5, base_delay=1.0):
    """
    Retry a function on database lock errors with exponential backoff.
    
    Args:
        func: Callable to execute
        max_retries: Maximum retry attempts (default 5)
        base_delay: Base delay in seconds (default 1.0)
    
    Returns:
        Result of func() or raises after max retries
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return func()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                last_error = e
                delay = base_delay * (2 ** attempt)  # Exponential backoff: 1, 2, 4, 8, 16 seconds
                print(f"    ⚠️  Database locked, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise
    raise last_error

# Request timeout
REQUEST_TIMEOUT = 10  # seconds


# ============================================================================
# PID-Based Daemon Monitoring Functions
# ============================================================================

def check_daemon_running(pid_file: Path, expected_script: str) -> Optional[bool]:
    """
    Check if daemon is running by PID file AND verify it's the right process.
    
    Returns:
        True: Daemon is running and verified
        False: Daemon is not running or PID mismatch
        None: Can't determine (file doesn't exist, etc.)
    """
    if not pid_file.exists():
        return None  # PID file doesn't exist - daemon never started or was cleaned up
    
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, IOError):
        return None  # Can't read PID file
    
    # Check if PID exists (signal 0 = just check, don't kill)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False  # Process doesn't exist
    except PermissionError:
        # Process exists but we can't signal it (shouldn't happen for our own daemons)
        pass
    
    # Verify it's actually our script (not a reused PID)
    try:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            cmdline = cmdline_path.read_text()
            # cmdline uses null bytes as separators
            if expected_script in cmdline:
                return True
            else:
                # PID exists but it's a different process (PID was reused)
                return False
    except (IOError, PermissionError):
        pass
    
    # Fallback: assume running if we got this far
    return True


def restart_daemon(daemon_name: str, script_path: Path, pid_file: Path, project_root: Path) -> bool:
    """
    Restart a sibling daemon using nohup.
    
    Returns True if restart command was sent successfully.
    """
    try:
        # Remove stale PID file
        if pid_file.exists():
            pid_file.unlink()
        
        # Find the log file path
        log_file = project_root / "logs" / f"{daemon_name}.log"
        
        # Get the Python interpreter from our venv
        python_path = sys.executable
        
        # Start the daemon with unbuffered output (-u flag)
        # This ensures print() statements are written immediately to the log file
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        
        # Start the daemon
        process = subprocess.Popen(
            [python_path, '-u', str(script_path)],
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # Detach from our process group
            cwd=str(project_root),
            env=env,
        )
        
        # Write new PID file
        pid_file.write_text(str(process.pid))
        
        return True
    except Exception as e:
        print(f"    ⚠️  Failed to restart {daemon_name}: {e}", file=sys.stderr)
        return False


def speak_daemon_down(daemon_name: str, project_root: Path, mode: str, will_restart: bool = True):
    """Speak notification that a sibling daemon is down."""
    friendly_names = {
        "reminder_scheduler": "the reminder scheduler",
        "follow_up_daemon": "the follow-up daemon",
        "jarvis_api": "the Jarvis API",
    }
    
    friendly = friendly_names.get(daemon_name, daemon_name)
    
    if will_restart:
        message = f"Hey Boss, {friendly} has crashed. I'm restarting it now."
    else:
        # For notify-only services like the API
        message = f"Hey Boss, {friendly} appears to be down. You may need to restart it manually."
    
    if mode == 'local':
        say_script = project_root / 'bin' / 'say-local.sh'
    else:
        say_script = project_root / 'bin' / 'say.sh'
    
    if say_script.exists():
        try:
            subprocess.run(
                [str(say_script), message],
                check=False,
                capture_output=True,
                text=True,
                timeout=15
            )
        except Exception as e:
            print(f"    ⚠️  TTS failed: {e}", file=sys.stderr)


def speak_daemon_recovered(daemon_name: str, project_root: Path, mode: str):
    """Speak notification that a sibling daemon has recovered."""
    friendly_names = {
        "reminder_scheduler": "The reminder scheduler",
        "follow_up_daemon": "The follow-up daemon",
        "jarvis_api": "The Jarvis API",
    }
    
    friendly = friendly_names.get(daemon_name, daemon_name)
    message = f"{friendly} is back up and running."
    
    if mode == 'local':
        say_script = project_root / 'bin' / 'say-local.sh'
    else:
        say_script = project_root / 'bin' / 'say.sh'
    
    if say_script.exists():
        try:
            subprocess.run(
                [str(say_script), message],
                check=False,
                capture_output=True,
                text=True,
                timeout=15
            )
        except Exception as e:
            print(f"    ⚠️  TTS failed: {e}", file=sys.stderr)


# ============================================================================
# Systemd Service Monitoring Functions
# ============================================================================

def check_service_exists(service_name: str) -> bool:
    """Check if a systemd service unit exists (is installed)."""
    try:
        result = subprocess.run(
            ["systemctl", "cat", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def check_service_active(service_name: str) -> Optional[bool]:
    """
    Check if systemd service is active.
    Returns: True if active, False if inactive/failed, None if service doesn't exist.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        status = result.stdout.strip()
        if status == "active":
            return True
        elif status in ("inactive", "failed", "dead"):
            return False
        else:
            # Unknown status - treat as not active
            return False
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        # systemctl not available
        return None
    except Exception:
        return None


def restart_service(service_name: str) -> bool:
    """Attempt to restart a systemd service."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"    ⚠️  Failed to restart {service_name}: {e}", file=sys.stderr)
        return False


def send_service_alert(service_name: str, project_root: Path, mode: str) -> bool:
    """Send alert to Jarvis API for a stopped service."""
    try:
        api_url = "http://localhost:8880/api/alerts"
        payload = {
            "title": f"Service Stopped: {service_name}",
            "description": f"Systemd service '{service_name}' is not running. Self-healing restart attempted.",
            "severity": "high",
            "source": "self-healing-daemon",
            "metadata": {
                "service": service_name,
                "host": os.uname().nodename
            }
        }
        
        response = requests.post(api_url, json=payload, timeout=30)
        return response.ok
    except Exception as e:
        print(f"    ⚠️  Failed to send alert: {e}", file=sys.stderr)
        return False


def speak_service_down(service_name: str, project_root: Path, mode: str):
    """Speak notification that a service is down."""
    # Friendly names for services
    friendly_names = {
        "jarvis-services": "Jarvis background services",
        "unifi-protect-webhook": "UniFi Protect webhook",
        "opencode-jarvis": "OpenCode Jarvis service",
    }
    
    friendly = friendly_names.get(service_name, service_name)
    message = f"Hey Boss, heads up. {friendly} has stopped. I'm attempting to restart it."
    
    if mode == 'local':
        say_script = project_root / 'bin' / 'say-local.sh'
    else:
        say_script = project_root / 'bin' / 'say.sh'
    
    if say_script.exists():
        try:
            subprocess.run(
                [str(say_script), message],
                check=False,
                capture_output=True,
                text=True,
                timeout=15
            )
        except Exception as e:
            print(f"    ⚠️  TTS failed: {e}", file=sys.stderr)


def speak_service_recovered(service_name: str, project_root: Path, mode: str):
    """Speak notification that a service has recovered."""
    friendly_names = {
        "jarvis-services": "Jarvis background services",
        "unifi-protect-webhook": "UniFi Protect webhook",
        "opencode-jarvis": "OpenCode Jarvis service",
    }
    
    friendly = friendly_names.get(service_name, service_name)
    message = f"Boss, good news. {friendly} is back up and running."
    
    if mode == 'local':
        say_script = project_root / 'bin' / 'say-local.sh'
    else:
        say_script = project_root / 'bin' / 'say.sh'
    
    if say_script.exists():
        try:
            subprocess.run(
                [str(say_script), message],
                check=False,
                capture_output=True,
                text=True,
                timeout=15
            )
        except Exception as e:
            print(f"    ⚠️  TTS failed: {e}", file=sys.stderr)


def get_alerts_to_check(db_path: str) -> List[Dict[str, Any]]:
    """Get pending alerts that have auto_resolve_url and are due for checking."""
    def _query():
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        alerts = cursor.execute("""
            SELECT * FROM alerts 
            WHERE status = 'pending'
            AND auto_resolve_url IS NOT NULL
            AND auto_resolve_url != ''
            ORDER BY severity DESC, created_at ASC
            LIMIT ?
        """, (MAX_CHECKS_PER_LOOP,)).fetchall()
        
        conn.close()
        return [dict(row) for row in alerts]
    
    return retry_on_db_lock(_query)


def should_check_now(alert: Dict[str, Any]) -> bool:
    """Determine if it's time to check this alert's URL."""
    check_interval = alert.get('auto_resolve_check_interval', 300)  # Default 5 min
    last_check_str = alert.get('last_check_at')
    
    if not last_check_str:
        # Never checked, check now
        return True
    
    try:
        last_check = datetime.fromisoformat(last_check_str)
    except (ValueError, TypeError):
        return True
    
    elapsed = datetime.now() - last_check
    return elapsed.total_seconds() >= check_interval


def check_url(url: str) -> bool:
    """
    Check if URL is responding successfully.
    Returns True if 2xx or 3xx status code.
    """
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            verify=True  # Verify SSL certificates
        )
        
        # Consider 2xx and 3xx as "resolved"
        return 200 <= response.status_code < 400
    
    except requests.exceptions.Timeout:
        return False
    except requests.exceptions.ConnectionError:
        return False
    except requests.exceptions.TooManyRedirects:
        return False
    except requests.exceptions.RequestException:
        return False
    except Exception:
        return False


def auto_resolve_alert(db_path: str, alert_id: int, alert_title: str, alert_source: str, mode: str, project_root: Path):
    """Mark alert as auto-resolved and notify user."""
    def _update():
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE alerts
            SET status = 'auto_resolved',
                resolved_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (now, now, alert_id))
        
        conn.commit()
        conn.close()
    
    retry_on_db_lock(_update)
    
    # Speak notification - extract specific item from title if possible
    if ':' in alert_title and ('Stopped' in alert_title or 'Down' in alert_title):
        # Extract specific thing (e.g., "Container Stopped: kokoro-cpu" -> "kokoro-cpu")
        item = alert_title.split(':')[-1].strip()
        message = f"Boss, good news! {item} is back up and running."
    else:
        # Generic message with source
        message = f"Boss, good news! {alert_source} is back up and running. Alert resolved."
    
    # Use appropriate TTS script
    if mode == 'local':
        say_script = project_root / 'bin' / 'say-local.sh'
    else:
        say_script = project_root / 'bin' / 'say.sh'
    
    if say_script.exists():
        try:
            subprocess.run(
                [str(say_script), message],
                check=False,
                capture_output=True,
                text=True,
                timeout=10
            )
        except Exception as e:
            print(f"Warning: TTS failed for alert {alert_id}: {e}", file=sys.stderr)


def update_last_check(db_path: str, alert_id: int):
    """Update last_check_at timestamp."""
    def _update():
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE alerts
            SET last_check_at = ?
            WHERE id = ?
        """, (now, alert_id))
        
        conn.commit()
        conn.close()
    
    retry_on_db_lock(_update)


def main():
    """Self-healing daemon main loop."""
    print("🩹 Self-Healing Daemon Starting...")
    
    # Load config
    load_config()
    mode = 'local' if get_config_value('LLM_PROVIDER', 'anthropic') == 'ollama' else 'cloud'
    
    project_root = Path(__file__).parent.parent
    db = MemoryDB()
    db_path = db.db_path
    
    # Initialize logger
    logger = ServiceLogger('self_healing_daemon')
    logger.log_startup(mode, {
        "database": str(db_path),
        "check_interval": 60,
        "max_checks_per_loop": MAX_CHECKS_PER_LOOP,
        "request_timeout": REQUEST_TIMEOUT,
        "monitored_systemd_services": list(MONITORED_SYSTEMD_SERVICES.keys()),
        "monitored_daemons": list(MONITORED_DAEMONS.keys()),
        "service_grace_period": SERVICE_GRACE_PERIOD,
        "daemon_grace_period": DAEMON_GRACE_PERIOD
    })
    
    print(f"   Mode: {mode}")
    print(f"   Database: {db_path}")
    print(f"   Check interval: 60 seconds")
    print(f"   Max checks per loop: {MAX_CHECKS_PER_LOOP}")
    print(f"   Request timeout: {REQUEST_TIMEOUT}s")
    
    # Discover which systemd services to monitor
    services_to_monitor = {}
    print(f"   Systemd service monitoring:")
    for service_name, config in MONITORED_SYSTEMD_SERVICES.items():
        exists = check_service_exists(service_name)
        if exists:
            services_to_monitor[service_name] = config
            print(f"     ✅ {service_name} (restart: {config['restart']})")
        elif config["required"]:
            print(f"     ⚠️  {service_name} - REQUIRED but not found!")
        else:
            print(f"     ⏭️  {service_name} - not installed, skipping")
    
    # Setup sibling daemon monitoring
    daemons_to_monitor = {}
    print(f"   Sibling daemon monitoring:")
    for daemon_name, config in MONITORED_DAEMONS.items():
        pid_file = project_root / config["pid_file"]
        notify_only = config.get("notify_only", False)
        
        # For notify_only daemons, we don't need a script path (we won't restart them)
        if notify_only:
            daemons_to_monitor[daemon_name] = {
                "pid_file": pid_file,
                "script_path": None,
                "script_name": config["script"],
                "restart": False,
                "notify_only": True,
            }
            print(f"     👁️  {daemon_name} (pid: {pid_file.name}, notify only)")
        else:
            script_path = project_root / "services" / config["script"]
            if script_path.exists():
                daemons_to_monitor[daemon_name] = {
                    "pid_file": pid_file,
                    "script_path": script_path,
                    "script_name": config["script"],
                    "restart": config.get("restart", True),
                    "notify_only": False,
                }
                print(f"     ✅ {daemon_name} (pid: {pid_file.name}, restart: {config.get('restart', True)})")
            else:
                print(f"     ⚠️  {daemon_name} - script not found: {script_path}")
    
    print(f"   Service grace period: {SERVICE_GRACE_PERIOD}s")
    print(f"   Daemon grace period: {DAEMON_GRACE_PERIOD}s")
    print()
    
    check_count = 0
    resolved_count = 0
    consecutive_errors = 0
    max_consecutive_errors = 10  # Only crash after 10 consecutive errors
    
    # Service monitoring state (systemd)
    service_down_since: Dict[str, datetime] = {}  # When service first went down
    service_alert_sent: Dict[str, bool] = {}  # Whether alert was sent
    service_last_status: Dict[str, bool] = {}  # Last known status
    
    # Daemon monitoring state (PID-based siblings)
    daemon_down_since: Dict[str, datetime] = {}  # When daemon first went down
    daemon_alert_sent: Dict[str, bool] = {}  # Whether alert was sent
    daemon_last_status: Dict[str, bool] = {}  # Last known status
    
    try:
        while True:
            try:
                check_count += 1
                current_time = datetime.now()
                time_str = current_time.strftime('%H:%M:%S')
                
                # ============================================================
                # Check systemd services (with grace period)
                # ============================================================
                for service_name, config in services_to_monitor.items():
                    is_active = check_service_active(service_name)
                    
                    if is_active is None:
                        # Can't check (systemctl not available)
                        continue
                    
                    prev_status = service_last_status.get(service_name)
                    
                    if is_active:
                        # Service is UP
                        if service_name in service_down_since:
                            del service_down_since[service_name]
                        
                        # Was it previously down and we sent an alert?
                        if service_alert_sent.get(service_name):
                            print(f"[{time_str}] ✅ SERVICE RECOVERED: {service_name}")
                            speak_service_recovered(service_name, project_root, mode)
                            logger.log_action("service_recovered", {
                                "service": service_name
                            }, success=True)
                            service_alert_sent[service_name] = False
                        elif prev_status == False:
                            # Recovered within grace period
                            print(f"[{time_str}] ✅ SERVICE ACTIVE: {service_name}")
                    
                    else:
                        # Service is DOWN
                        if service_name not in service_down_since:
                            # First time seeing it down - start grace period
                            service_down_since[service_name] = current_time
                            print(f"[{time_str}] ⚠️  SERVICE DOWN: {service_name} (grace period started, {SERVICE_GRACE_PERIOD}s)")
                        else:
                            # Already down - check if grace period exceeded
                            elapsed = (current_time - service_down_since[service_name]).total_seconds()
                            
                            if elapsed >= SERVICE_GRACE_PERIOD and not service_alert_sent.get(service_name):
                                # Grace period exceeded - alert and attempt restart
                                print(f"[{time_str}] ❌ SERVICE STOPPED: {service_name} (down for {int(elapsed)}s)")
                                
                                # Send alert
                                send_service_alert(service_name, project_root, mode)
                                
                                # Speak notification
                                speak_service_down(service_name, project_root, mode)
                                
                                # Log
                                logger.log_action("service_down", {
                                    "service": service_name,
                                    "down_since": service_down_since[service_name].isoformat(),
                                    "elapsed_seconds": int(elapsed)
                                }, success=False)
                                
                                service_alert_sent[service_name] = True
                                
                                # Attempt self-healing restart
                                if config.get("restart", True):
                                    print(f"           🔄 Attempting restart...")
                                    if restart_service(service_name):
                                        print(f"           ✅ Restart command sent")
                                        logger.log_action("service_restart", {
                                            "service": service_name
                                        }, success=True)
                                    else:
                                        print(f"           ⚠️  Restart failed")
                                        logger.log_action("service_restart", {
                                            "service": service_name
                                        }, success=False)
                    
                    service_last_status[service_name] = is_active
                
                # ============================================================
                # Check sibling daemons (PID-based, with grace period)
                # ============================================================
                for daemon_name, config in daemons_to_monitor.items():
                    pid_file = config["pid_file"]
                    script_name = config["script_name"]
                    
                    is_running = check_daemon_running(pid_file, script_name)
                    prev_status = daemon_last_status.get(daemon_name)
                    
                    if is_running is None:
                        # PID file doesn't exist - daemon may not have started yet
                        # Don't alert on first check
                        if prev_status is not None and prev_status == True:
                            # Was running before, now PID file gone
                            is_running = False
                        else:
                            daemon_last_status[daemon_name] = None
                            continue
                    
                    if is_running:
                        # Daemon is UP
                        if daemon_name in daemon_down_since:
                            del daemon_down_since[daemon_name]
                        
                        # Was it previously down and we sent an alert?
                        if daemon_alert_sent.get(daemon_name):
                            print(f"[{time_str}] ✅ DAEMON RECOVERED: {daemon_name}")
                            speak_daemon_recovered(daemon_name, project_root, mode)
                            logger.log_action("daemon_recovered", {
                                "daemon": daemon_name
                            }, success=True)
                            daemon_alert_sent[daemon_name] = False
                        elif prev_status == False:
                            # Recovered within grace period
                            print(f"[{time_str}] ✅ DAEMON RUNNING: {daemon_name}")
                    
                    else:
                        # Daemon is DOWN
                        if daemon_name not in daemon_down_since:
                            # First time seeing it down - start grace period
                            daemon_down_since[daemon_name] = current_time
                            print(f"[{time_str}] ⚠️  DAEMON DOWN: {daemon_name} (grace period started, {DAEMON_GRACE_PERIOD}s)")
                        else:
                            # Already down - check if grace period exceeded
                            elapsed = (current_time - daemon_down_since[daemon_name]).total_seconds()
                            
                            if elapsed >= DAEMON_GRACE_PERIOD and not daemon_alert_sent.get(daemon_name):
                                # Grace period exceeded - alert and attempt restart
                                will_restart = config.get("restart", True) and not config.get("notify_only", False)
                                print(f"[{time_str}] ❌ DAEMON DOWN: {daemon_name} (down for {int(elapsed)}s)")
                                
                                # Speak notification (with appropriate message based on restart intent)
                                speak_daemon_down(daemon_name, project_root, mode, will_restart=will_restart)
                                
                                # Log
                                logger.log_action("daemon_down", {
                                    "daemon": daemon_name,
                                    "down_since": daemon_down_since[daemon_name].isoformat(),
                                    "elapsed_seconds": int(elapsed),
                                    "will_restart": will_restart
                                }, success=False)
                                
                                daemon_alert_sent[daemon_name] = True
                                
                                # Attempt self-healing restart (unless notify_only)
                                if will_restart:
                                    print(f"           🔄 Attempting restart...")
                                    if restart_daemon(
                                        daemon_name,
                                        config["script_path"],
                                        pid_file,
                                        project_root
                                    ):
                                        print(f"           ✅ Restart command sent (new PID written)")
                                        logger.log_action("daemon_restart", {
                                            "daemon": daemon_name
                                        }, success=True)
                                        # Clear down tracking so we recheck
                                        del daemon_down_since[daemon_name]
                                    else:
                                        print(f"           ⚠️  Restart failed")
                                        logger.log_action("daemon_restart", {
                                            "daemon": daemon_name
                                        }, success=False)
                                else:
                                    print(f"           ℹ️  Notify only - manual restart required")
                    
                    daemon_last_status[daemon_name] = is_running
                
                # ============================================================
                # Check alerts with auto_resolve_url (existing functionality)
                # ============================================================
                
                # Get alerts with auto_resolve_url
                alerts_to_check = get_alerts_to_check(db_path)
                consecutive_errors = 0  # Reset on success
                
                logger.log_check(len(alerts_to_check), {"with_auto_resolve_url": len(alerts_to_check)})
                
                if len(alerts_to_check) > 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Check #{check_count}: {len(alerts_to_check)} alerts with auto_resolve_url")
                    
                    for alert in alerts_to_check:
                        if not should_check_now(alert):
                            continue
                        
                        alert_id = alert['id']
                        title = alert['title']
                        source = alert.get('source', 'Unknown')
                        url = alert['auto_resolve_url']
                        
                        print(f"  → Checking alert {alert_id}: {title}")
                        print(f"    URL: {url}")
                        
                        try:
                            # Check URL
                            is_resolved = check_url(url)
                            
                            # Update last check time
                            update_last_check(db_path, alert_id)
                            
                            # Log URL check
                            logger.log_action("url_check", {
                                "alert_id": alert_id,
                                "title": title,
                                "url": url
                            }, success=is_resolved)
                            
                            if is_resolved:
                                print(f"    ✅ RESOLVED - Auto-canceling alert")
                                auto_resolve_alert(db_path, alert_id, title, source, mode, project_root)
                                
                                # Log auto-resolve
                                logger.log_action("auto_resolve", {
                                    "alert_id": alert_id,
                                    "title": title,
                                    "source": source,
                                    "url": url
                                }, success=True)
                                
                                resolved_count += 1
                            else:
                                print(f"    ⏳ Still down")
                        
                        except Exception as e:
                            logger.log_error(f"Check failed for alert {alert_id}", {
                                "alert_id": alert_id,
                                "url": url,
                                "error": str(e)
                            })
                            print(f"    ⚠️  Error: {e}")
                
                # Wait before next check
                time.sleep(60)
                
            except sqlite3.OperationalError as e:
                consecutive_errors += 1
                logger.log_error(f"Database error (attempt {consecutive_errors}): {e}")
                print(f"\n⚠️  Database error: {e} (attempt {consecutive_errors}/{max_consecutive_errors})", file=sys.stderr)
                if consecutive_errors >= max_consecutive_errors:
                    print(f"\n❌ Too many consecutive errors, shutting down", file=sys.stderr)
                    logger.log_shutdown({"reason": "too_many_errors", "last_error": str(e)})
                    sys.exit(1)
                time.sleep(30)  # Wait longer after DB errors
                
            except Exception as e:
                consecutive_errors += 1
                logger.log_error(f"Unexpected error (attempt {consecutive_errors}): {e}")
                print(f"\n⚠️  Error: {e} (attempt {consecutive_errors}/{max_consecutive_errors})", file=sys.stderr)
                if consecutive_errors >= max_consecutive_errors:
                    print(f"\n❌ Too many consecutive errors, shutting down", file=sys.stderr)
                    logger.log_shutdown({"reason": "too_many_errors", "last_error": str(e)})
                    sys.exit(1)
                time.sleep(60)  # Continue checking after transient errors
    
    except KeyboardInterrupt:
        print(f"\n✋ Self-Healing Daemon stopped by user")
        print(f"   Total resolved: {resolved_count}")
        logger.log_shutdown({"total_resolved": resolved_count, "checks": check_count})


if __name__ == "__main__":
    main()

