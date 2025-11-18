#!/usr/bin/env python3
"""
Reminder Scheduler Daemon
Checks for reminders that are due and triggers them.

Checks every 60 seconds for reminders with trigger_time <= now.
"""

import sys
import os
import time
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB
from service_logger import ServiceLogger


def get_due_reminders(db_path: str) -> List[Dict[str, Any]]:
    """Get reminders that are due (trigger_time <= now)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    reminders = cursor.execute("""
        SELECT * FROM reminders 
        WHERE status = 'scheduled'
        AND trigger_time <= ?
        ORDER BY trigger_time ASC
    """, (now,)).fetchall()
    
    conn.close()
    return [dict(row) for row in reminders]


def speak_reminder(reminder: Dict[str, Any], mode: str, project_root: Path):
    """Speak reminder via TTS."""
    title = reminder.get('title', 'Reminder')
    description = reminder.get('description', '')
    
    # Build message
    message = f"Boss, reminder: {title}"
    if description:
        message += f". {description}"
    
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
                timeout=15
            )
        except Exception as e:
            print(f"Warning: TTS failed for reminder {reminder['id']}: {e}", file=sys.stderr)


def mark_reminder_triggered(db_path: str, reminder_id: int):
    """Mark reminder as triggered."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute("""
        UPDATE reminders
        SET status = 'triggered',
            triggered_at = ?,
            spoken = 1,
            spoken_at = ?
        WHERE id = ?
    """, (now, now, reminder_id))
    
    conn.commit()
    conn.close()


def call_callback_url(url: str):
    """Call webhook callback URL if provided."""
    try:
        import requests
        response = requests.post(url, timeout=10)
        return response.ok
    except Exception as e:
        print(f"Warning: Callback failed: {e}", file=sys.stderr)
        return False


def main():
    """Reminder scheduler daemon main loop."""
    print("⏰ Reminder Scheduler Starting...")
    
    # Load config
    load_config()
    mode = 'local' if get_config_value('LLM_PROVIDER', 'anthropic') == 'ollama' else 'cloud'
    
    project_root = Path(__file__).parent.parent
    db = MemoryDB()
    db_path = db.db_path
    
    # Initialize logger
    logger = ServiceLogger('reminder_scheduler')
    logger.log_startup(mode, {
        "database": str(db_path),
        "check_interval": 60
    })
    
    print(f"   Mode: {mode}")
    print(f"   Database: {db_path}")
    print(f"   Check interval: 60 seconds")
    print()
    
    check_count = 0
    triggered_count = 0
    
    try:
        while True:
            check_count += 1
            
            # Get due reminders
            due_reminders = get_due_reminders(db_path)
            
            logger.log_check(len(due_reminders), {"due_reminders": len(due_reminders)})
            
            if len(due_reminders) > 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Check #{check_count}: {len(due_reminders)} due reminders")
                
                for reminder in due_reminders:
                    reminder_id = reminder['id']
                    title = reminder['title']
                    trigger_time = reminder['trigger_time']
                    callback_url = reminder.get('callback_url')
                    
                    print(f"  → Triggering reminder {reminder_id}: {title}")
                    print(f"    Scheduled for: {trigger_time}")
                    
                    try:
                        # Speak reminder
                        speak_reminder(reminder, mode, project_root)
                        
                        # Mark as triggered
                        mark_reminder_triggered(db_path, reminder_id)
                        
                        # Log trigger action
                        logger.log_action("trigger_reminder", {
                            "reminder_id": reminder_id,
                            "title": title,
                            "trigger_time": trigger_time
                        }, success=True)
                        
                        # Call callback if provided
                        if callback_url:
                            print(f"    Calling callback: {callback_url}")
                            success = call_callback_url(callback_url)
                            if success:
                                print(f"    ✅ Callback succeeded")
                            else:
                                print(f"    ⚠️  Callback failed")
                                logger.log_error(f"Callback failed for reminder {reminder_id}", {
                                    "reminder_id": reminder_id,
                                    "callback_url": callback_url
                                })
                        
                        triggered_count += 1
                    
                    except Exception as e:
                        logger.log_error(f"Failed to trigger reminder {reminder_id}", {
                            "reminder_id": reminder_id,
                            "error": str(e)
                        })
                        print(f"    ⚠️  Error: {e}")
            
            # Wait before next check
            time.sleep(60)
    
    except KeyboardInterrupt:
        print(f"\n✋ Reminder Scheduler stopped by user")
        print(f"   Total triggered: {triggered_count}")
        logger.log_shutdown({"total_triggered": triggered_count, "checks": check_count})
    except Exception as e:
        logger.log_error(f"Fatal error: {e}")
        print(f"\n❌ Reminder Scheduler error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

