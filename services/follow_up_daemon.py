#!/usr/bin/env python3
"""
Follow-Up Daemon
Periodically checks for pending alerts and re-notifies if not acknowledged.

Escalation schedule (configurable):
- High/Critical: 15 min, 30 min, 60 min
- Medium: 30 min, 60 min, 120 min  
- Low: 60 min, 180 min, 360 min
"""

import sys
import time
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value, get_active_config_mode
from memory_db import MemoryDB
from service_logger import ServiceLogger
from tts_normalizer import normalize_tts_text


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


# Follow-up schedules (minutes between reminders)
FOLLOW_UP_SCHEDULE = {
    "critical": [15, 30, 60],
    "high": [15, 30, 60],
    "medium": [30, 60, 120],
    "low": [60, 180, 360]
}

# Maximum follow-ups before giving up
MAX_FOLLOW_UPS = 3


def get_pending_alerts(db_path: str) -> List[Dict[str, Any]]:
    """Get all pending alerts that need follow-up."""
    def _query():
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        alerts = cursor.execute("""
            SELECT * FROM alerts 
            WHERE status = 'pending'
            AND follow_up_count < ?
            ORDER BY severity DESC, created_at ASC
        """, (MAX_FOLLOW_UPS,)).fetchall()
        
        conn.close()
        return [dict(row) for row in alerts]
    
    return retry_on_db_lock(_query)


def should_follow_up(alert: Dict[str, Any]) -> bool:
    """Determine if alert needs follow-up based on time elapsed."""
    severity = alert.get('severity', 'medium')
    follow_up_count = alert.get('follow_up_count', 0)
    
    # Get schedule for this severity
    schedule = FOLLOW_UP_SCHEDULE.get(severity, FOLLOW_UP_SCHEDULE['medium'])
    
    # If we've exceeded the schedule length, stop following up
    if follow_up_count >= len(schedule):
        return False
    
    # Determine which timestamp to use
    last_time_str = alert.get('last_follow_up') or alert.get('spoken_at') or alert.get('created_at')
    
    if not last_time_str:
        return False
    
    try:
        last_time = datetime.fromisoformat(last_time_str)
    except (ValueError, TypeError):
        return False
    
    # Time since last follow-up/creation
    elapsed = datetime.now() - last_time
    
    # Get required wait time for current follow-up
    required_wait_minutes = schedule[follow_up_count]
    required_wait = timedelta(minutes=required_wait_minutes)
    
    return elapsed >= required_wait


def speak_follow_up(alert: Dict[str, Any], mode: str, project_root: Path):
    """Speak follow-up alert via TTS (uses caching for repeated messages)."""
    title = alert.get('title', 'Unknown alert')
    severity = alert.get('severity', 'medium')
    follow_up_count = alert.get('follow_up_count', 0)
    
    # Build message
    if follow_up_count == 0:
        prefix = "First reminder:"
    elif follow_up_count == 1:
        prefix = "Second reminder:"
    elif follow_up_count == 2:
        prefix = "Final reminder:"
    else:
        prefix = "Reminder:"
    
    if severity in ['critical', 'high']:
        message = f"Boss, {prefix} {title} is still pending."
    else:
        message = f"{prefix} {title}"

    profile = None
    if alert.get('source') == 'unifi-protect':
        profile = 'camera_alert'
    elif alert.get('source') == 'price_monitor':
        profile = 'price_quote'
    
    # Use say-status.sh which has caching for repeated phrases
    if mode == 'local':
        say_script = project_root / 'bin' / 'say-status-local.sh'
    else:
        say_script = project_root / 'bin' / 'say-status.sh'
    
    # Fallback to regular say.sh if say-status doesn't exist
    if not say_script.exists():
        if mode == 'local':
            say_script = project_root / 'bin' / 'say-local.sh'
        else:
            say_script = project_root / 'bin' / 'say.sh'
    
    if say_script.exists():
        try:
            spoken_message = normalize_tts_text(message, profile=profile)
            if not spoken_message:
                return
            subprocess.run(
                [str(say_script), spoken_message],
                check=False,
                capture_output=True,
                text=True,
                timeout=10
            )
        except Exception as e:
            print(f"Warning: TTS failed for alert {alert['id']}: {e}", file=sys.stderr)


def update_follow_up(db_path: str, alert_id: int):
    """Mark alert as followed up."""
    def _update():
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        
        cursor.execute("""
            UPDATE alerts
            SET follow_up_count = follow_up_count + 1,
                last_follow_up = ?,
                updated_at = ?
            WHERE id = ?
        """, (now, now, alert_id))
        
        conn.commit()
        conn.close()
    
    retry_on_db_lock(_update)


def main():
    """Follow-up daemon main loop."""
    print("🔄 Follow-Up Daemon Starting...")
    
    # Load config
    load_config()
    mode = get_active_config_mode()
    
    project_root = Path(__file__).parent.parent
    db = MemoryDB()
    db_path = db.db_path
    
    # Initialize logger
    logger = ServiceLogger('follow_up_daemon')
    logger.log_startup(mode, {
        "database": str(db_path),
        "check_interval": 60,
        "max_follow_ups": MAX_FOLLOW_UPS,
        "schedule": FOLLOW_UP_SCHEDULE
    })
    
    print(f"   Mode: {mode}")
    print(f"   Database: {db_path}")
    print(f"   Check interval: 60 seconds")
    print(f"   Max follow-ups: {MAX_FOLLOW_UPS}")
    print()
    
    check_count = 0
    total_follow_ups = 0
    consecutive_errors = 0
    max_consecutive_errors = 10  # Only crash after 10 consecutive errors
    
    try:
        while True:
            try:
                check_count += 1
                
                # Get pending alerts
                pending_alerts = get_pending_alerts(db_path)
                consecutive_errors = 0  # Reset on success
                
                logger.log_check(len(pending_alerts), {"pending_count": len(pending_alerts)})
                
                if len(pending_alerts) > 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Check #{check_count}: {len(pending_alerts)} pending alerts")
                    
                    for alert in pending_alerts:
                        if should_follow_up(alert):
                            alert_id = alert['id']
                            title = alert['title']
                            severity = alert['severity']
                            follow_up_count = alert.get('follow_up_count', 0)
                            
                            print(f"  → Follow-up #{follow_up_count + 1} for alert {alert_id}: {title} ({severity})")
                            
                            try:
                                # Speak alert
                                speak_follow_up(alert, mode, project_root)
                                
                                # Update database
                                update_follow_up(db_path, alert_id)
                                
                                # Log action
                                logger.log_action("follow_up", {
                                    "alert_id": alert_id,
                                    "title": title,
                                    "severity": severity,
                                    "follow_up_count": follow_up_count + 1
                                }, success=True)
                                
                                total_follow_ups += 1
                            
                            except Exception as e:
                                logger.log_error(f"Follow-up failed for alert {alert_id}", {
                                    "alert_id": alert_id,
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
        print("\n✋ Follow-Up Daemon stopped by user")
        logger.log_shutdown({"total_follow_ups": total_follow_ups, "checks": check_count})


if __name__ == "__main__":
    main()
