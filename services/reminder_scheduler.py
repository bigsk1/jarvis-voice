#!/usr/bin/env python3
"""
Reminder Scheduler Daemon
Checks for reminders that are due and triggers them.

Checks every 60 seconds for reminders with trigger_time <= now.
"""

import sys
import time
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB
from service_logger import ServiceLogger


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


def get_due_reminders(db_path: str) -> List[Dict[str, Any]]:
    """Get reminders that are due (trigger_time <= now)."""
    def _query():
        conn = sqlite3.connect(db_path, timeout=30)  # 30 second timeout
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Use UTC time to match the database (trigger_time is stored in UTC)
        now = datetime.now(timezone.utc).isoformat()
        
        reminders = cursor.execute("""
            SELECT * FROM reminders 
            WHERE status = 'scheduled'
            AND trigger_time <= ?
            ORDER BY trigger_time ASC
        """, (now,)).fetchall()
        
        conn.close()
        return [dict(row) for row in reminders]
    
    return retry_on_db_lock(_query)


def speak_reminder(reminder: Dict[str, Any], mode: str, project_root: Path):
    """Speak reminder via TTS."""
    title = reminder.get('title', 'Reminder')
    description = reminder.get('description', '')
    recurrence_rule = reminder.get('recurrence_rule')
    
    # Build message
    message = f"Boss, reminder: {title}"
    if description:
        message += f". {description}"
    
    # Add recurring info if applicable
    if recurrence_rule:
        if recurrence_rule.startswith("WEEKLY:"):
            days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            day_num = int(recurrence_rule.split(':')[1])
            message += f". This is a weekly reminder, rescheduled for next {days[day_num]}."
        elif recurrence_rule.startswith("MONTHLY:"):
            day = recurrence_rule.split(':')[1]
            message += f". This is a monthly reminder, rescheduled for the {day}th of next month."
    
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


def calculate_next_occurrence(current_trigger: str, recurrence_rule: str) -> str:
    """Calculate next occurrence for recurring reminder.
    
    Args:
        current_trigger: Current trigger time (ISO format UTC)
        recurrence_rule: "WEEKLY:X" or "MONTHLY:X"
    
    Returns:
        Next trigger time (ISO format UTC)
    """
    from datetime import datetime, timedelta
    
    current = datetime.fromisoformat(current_trigger.replace('Z', '+00:00'))
    if current.tzinfo:
        current = current.replace(tzinfo=None)
    
    if recurrence_rule.startswith("WEEKLY:"):
        # Add 7 days for weekly recurrence
        next_trigger = current + timedelta(days=7)
        return next_trigger.isoformat()
    
    elif recurrence_rule.startswith("MONTHLY:"):
        # Add 1 month for monthly recurrence
        target_day = int(recurrence_rule.split(':')[1])
        
        # Move to next month
        if current.month == 12:
            next_trigger = current.replace(year=current.year + 1, month=1)
        else:
            next_trigger = current.replace(month=current.month + 1)
        
        # Try to set to target day
        try:
            next_trigger = next_trigger.replace(day=target_day)
        except ValueError:
            # Day doesn't exist in this month (e.g., Feb 30), skip to next month
            if next_trigger.month == 12:
                next_trigger = next_trigger.replace(year=next_trigger.year + 1, month=1, day=target_day)
            else:
                next_trigger = next_trigger.replace(month=next_trigger.month + 1, day=target_day)
        
        return next_trigger.isoformat()
    
    return None


def mark_reminder_triggered(db_path: str, reminder_id: int, recurrence_rule: str = None, current_trigger: str = None):
    """Mark reminder as triggered, or reschedule if recurring."""
    def _update():
        conn = sqlite3.connect(db_path, timeout=30)  # 30 second timeout
        cursor = conn.cursor()
        
        # Use UTC time for consistency
        now = datetime.now(timezone.utc).isoformat()
        
        if recurrence_rule:
            # Recurring reminder - calculate next occurrence and reschedule
            next_trigger = calculate_next_occurrence(current_trigger, recurrence_rule)
            
            if next_trigger:
                cursor.execute("""
                    UPDATE reminders
                    SET status = 'scheduled',
                        trigger_time = ?,
                        triggered_at = ?,
                        spoken = 1,
                        spoken_at = ?
                    WHERE id = ?
                """, (next_trigger, now, now, reminder_id))
            else:
                # Fallback: just mark as triggered if calculation fails
                cursor.execute("""
                    UPDATE reminders
                    SET status = 'triggered',
                        triggered_at = ?,
                        spoken = 1,
                        spoken_at = ?
                    WHERE id = ?
                """, (now, now, reminder_id))
        else:
            # One-time reminder - mark as triggered
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
    
    retry_on_db_lock(_update)


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
    
    consecutive_errors = 0
    max_consecutive_errors = 10  # Only crash after 10 consecutive errors
    
    try:
        while True:
            try:
                check_count += 1
                
                # Get due reminders
                due_reminders = get_due_reminders(db_path)
                consecutive_errors = 0  # Reset on success
                
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
                            
                            # Mark as triggered or reschedule if recurring
                            mark_reminder_triggered(
                                db_path, 
                                reminder_id,
                                recurrence_rule=reminder.get('recurrence_rule'),
                                current_trigger=reminder['trigger_time']
                            )
                            
                            # Log trigger action
                            recurrence_info = f" (recurring: {reminder.get('recurrence_rule')})" if reminder.get('recurrence_rule') else ""
                            logger.log_action("trigger_reminder", {
                                "reminder_id": reminder_id,
                                "title": title,
                                "trigger_time": trigger_time,
                                "recurrence_rule": reminder.get('recurrence_rule')
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
        print(f"\n✋ Reminder Scheduler stopped by user")
        print(f"   Total triggered: {triggered_count}")
        logger.log_shutdown({"total_triggered": triggered_count, "checks": check_count})


if __name__ == "__main__":
    main()

