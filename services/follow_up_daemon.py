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
import os
import time
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB
from service_logger import ServiceLogger


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
    conn = sqlite3.connect(db_path)
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
            subprocess.run(
                [str(say_script), message],
                check=False,
                capture_output=True,
                text=True,
                timeout=10
            )
        except Exception as e:
            print(f"Warning: TTS failed for alert {alert['id']}: {e}", file=sys.stderr)


def update_follow_up(db_path: str, alert_id: int):
    """Mark alert as followed up."""
    conn = sqlite3.connect(db_path)
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


def main():
    """Follow-up daemon main loop."""
    print("🔄 Follow-Up Daemon Starting...")
    
    # Load config
    load_config()
    mode = 'local' if get_config_value('LLM_PROVIDER', 'anthropic') == 'ollama' else 'cloud'
    
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
    
    try:
        while True:
            check_count += 1
            
            # Get pending alerts
            pending_alerts = get_pending_alerts(db_path)
            
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
    
    except KeyboardInterrupt:
        print("\n✋ Follow-Up Daemon stopped by user")
        logger.log_shutdown({"total_follow_ups": total_follow_ups, "checks": check_count})
    except Exception as e:
        logger.log_error(f"Fatal error: {e}")
        print(f"\n❌ Follow-Up Daemon error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

