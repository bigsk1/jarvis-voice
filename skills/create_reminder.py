#!/usr/bin/env python3
"""
Create Reminder Tool
Creates time-based reminders that trigger TTS notifications.

Input: {
    "title": "Reminder title",
    "description": "Optional details",
    "when": "Natural time expression (e.g., 'in 4 hours', 'tomorrow at 3pm', 'in 30 minutes')"
}

Output: {
    "ok": bool,
    "speech": str,
    "data": {
        "reminder_id": int,
        "trigger_time": str,
        "trigger_time_local": str
    }
}
"""

import sys
import os
import json
import re
from datetime import datetime, timedelta, timezone

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB

def parse_recurrence(when: str):
    """Parse recurring patterns from time expression.
    
    Returns: recurrence_rule string or None
    - "WEEKLY:1" for every Monday (0=Mon, 6=Sun)
    - "MONTHLY:10" for 10th of each month
    - None if not recurring
    """
    when_lower = when.lower()
    
    # "every wednesday" or "every week on wednesday"
    days_of_week = {
        'monday': 0, 'mon': 0,
        'tuesday': 1, 'tue': 1, 'tues': 1,
        'wednesday': 2, 'wed': 2,
        'thursday': 3, 'thu': 3, 'thurs': 3,
        'friday': 4, 'fri': 4,
        'saturday': 5, 'sat': 5,
        'sunday': 6, 'sun': 6
    }
    
    if when_lower.startswith('every '):
        when_lower = when_lower[6:].strip()  # Remove "every "
        
        # Check for "month on the Xth" or "month on Xth" FIRST (before day names)
        month_match = re.search(r'month\s+(?:on\s+)?(?:the\s+)?(\d+)(?:st|nd|rd|th)?', when_lower)
        if month_match:
            day = int(month_match.group(1))
            if 1 <= day <= 31:
                return f"MONTHLY:{day}"
        
        # Check for day of week
        for day_name, day_num in days_of_week.items():
            if day_name in when_lower:
                return f"WEEKLY:{day_num}"
    
    return None


def parse_time_expression(when: str, default_hour: int = 10):
    """Parse natural time expressions into datetime.
    
    Args:
        when: Natural language time expression
        default_hour: Default hour to use when time not specified (default 10am)
    
    Returns:
        tuple: (trigger_datetime, recurrence_rule or None)
    
    Examples:
    - "in 30 minutes" -> (datetime, None)
    - "every wednesday" -> (next Wed 10am, "WEEKLY:2")
    - "every month on the 10th" -> (next 10th 10am, "MONTHLY:10")
    - "tomorrow at 3pm" -> (datetime, None)
    """
    when = when.lower().strip()
    now = datetime.now()
    
    # Check for recurring patterns first
    recurrence = parse_recurrence(when)
    
    # If recurring, calculate first trigger time
    if recurrence:
        rule = recurrence
        
        if rule.startswith("WEEKLY:"):
            target_weekday = int(rule.split(':')[1])
            days_ahead = (target_weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week if today
            
            trigger_time = now + timedelta(days=days_ahead)
            
            # Extract time from expression if provided, else use default
            time_match = re.search(r'(\d+)(?::(\d+))?\s*(am|pm)', when)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                meridiem = time_match.group(3)
                
                if meridiem == 'pm' and hour != 12:
                    hour += 12
                elif meridiem == 'am' and hour == 12:
                    hour = 0
                
                trigger_time = trigger_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                trigger_time = trigger_time.replace(hour=default_hour, minute=0, second=0, microsecond=0)
            
            return trigger_time, rule
        
        elif rule.startswith("MONTHLY:"):
            target_day = int(rule.split(':')[1])
            
            # Find next occurrence of this day
            trigger_time = now.replace(day=1, hour=default_hour, minute=0, second=0, microsecond=0)
            
            # Try this month
            try:
                trigger_time = trigger_time.replace(day=target_day)
                if trigger_time <= now:
                    # Next month
                    if trigger_time.month == 12:
                        trigger_time = trigger_time.replace(year=trigger_time.year + 1, month=1, day=target_day)
                    else:
                        trigger_time = trigger_time.replace(month=trigger_time.month + 1, day=target_day)
            except ValueError:
                # Day doesn't exist in this month, try next month
                if trigger_time.month == 12:
                    trigger_time = trigger_time.replace(year=trigger_time.year + 1, month=1, day=target_day)
                else:
                    trigger_time = trigger_time.replace(month=trigger_time.month + 1, day=target_day)
            
            # Extract time if provided
            time_match = re.search(r'(\d+)(?::(\d+))?\s*(am|pm)', when)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                meridiem = time_match.group(3)
                
                if meridiem == 'pm' and hour != 12:
                    hour += 12
                elif meridiem == 'am' and hour == 12:
                    hour = 0
                
                trigger_time = trigger_time.replace(hour=hour, minute=minute)
            
            return trigger_time, rule
    
    # Pattern: "in X minutes/hours/days" (one-time)
    if when.startswith("in "):
        when = when[3:].strip()  # Remove "in "
        
        # Handle compound times like "1 hour 30 minutes"
        total_delta = timedelta()
        
        # Extract all time components
        minutes_match = re.search(r'(\d+)\s*(?:minute|min|m)s?', when)
        hours_match = re.search(r'(\d+)\s*(?:hour|hr|h)s?', when)
        days_match = re.search(r'(\d+)\s*(?:day|d)s?', when)
        
        if minutes_match:
            total_delta += timedelta(minutes=int(minutes_match.group(1)))
        if hours_match:
            total_delta += timedelta(hours=int(hours_match.group(1)))
        if days_match:
            total_delta += timedelta(days=int(days_match.group(1)))
        
        if total_delta.total_seconds() > 0:
            return now + total_delta, None
        else:
            raise ValueError(f"Could not parse time from: {when}")
    
    # Pattern: "tomorrow at 3pm" (one-time)
    if "tomorrow" in when:
        tomorrow = now + timedelta(days=1)
        
        # Check for specific time
        time_match = re.search(r'(\d+)\s*(am|pm)', when)
        if time_match:
            hour = int(time_match.group(1))
            meridiem = time_match.group(2)
            
            if meridiem == 'pm' and hour != 12:
                hour += 12
            elif meridiem == 'am' and hour == 12:
                hour = 0
            
            return tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0), None
        else:
            # Just "tomorrow" - default to 10am
            return tomorrow.replace(hour=default_hour, minute=0, second=0, microsecond=0), None
    
    # Pattern: "at 3pm" or "3pm" (one-time)
    time_match = re.search(r'(\d+)(?::(\d+))?\s*(am|pm)', when)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        meridiem = time_match.group(3)
        
        if meridiem == 'pm' and hour != 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
        
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # If time has passed today, schedule for tomorrow
        if target <= now:
            target += timedelta(days=1)
        
        return target, None
    
    # Pattern: "on the 10th" or "the 10th" (one-time, default to 10am)
    date_match = re.search(r'(?:on\s+)?(?:the\s+)?(\d+)(?:st|nd|rd|th)?', when)
    if date_match:
        day = int(date_match.group(1))
        if 1 <= day <= 31:
            target = now.replace(day=day, hour=default_hour, minute=0, second=0, microsecond=0)
            
            # If day has passed this month, next month
            if target <= now:
                if target.month == 12:
                    target = target.replace(year=target.year + 1, month=1)
                else:
                    target = target.replace(month=target.month + 1)
            
            return target, None
    
    raise ValueError(f"Could not parse time expression: {when}")


def format_local_time(dt: datetime) -> str:
    """Format datetime in human-readable local time."""
    return dt.strftime("%A, %B %d at %I:%M %p")


def main():
    try:
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        # Load config
        load_config()
        
        # Extract parameters
        title = args.get('title')
        if not title:
            raise ValueError("title is required")
        
        description = args.get('description', '')
        when = args.get('when')
        if not when:
            raise ValueError("when is required (e.g., 'in 4 hours', 'tomorrow at 3pm')")
        
        # Parse time (returns tuple: datetime, recurrence_rule)
        trigger_time_local, recurrence_rule = parse_time_expression(when)
        
        # Convert to UTC for storage
        # Note: This assumes system timezone is set correctly
        utc_offset = datetime.now() - datetime.now(timezone.utc).replace(tzinfo=None)
        trigger_time_utc = trigger_time_local - utc_offset
        
        # Create reminder in database
        import sqlite3
        db = MemoryDB()
        
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO reminders (
                title, description, trigger_time, status,
                created_at, spoken, spoken_at, triggered_at,
                acknowledged_at, callback_url, recurrence_rule,
                related_intel_file, metadata
            ) VALUES (?, ?, ?, 'scheduled', ?, 0, NULL, NULL, NULL, NULL, ?, NULL, NULL)
        """, (
            title,
            description,
            trigger_time_utc.isoformat(),
            datetime.now(timezone.utc).isoformat(),
            recurrence_rule
        ))
        
        reminder_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Format response
        time_str = format_local_time(trigger_time_local)
        
        if recurrence_rule:
            speech = f"Recurring reminder set: {title}. First trigger {time_str}"
        else:
            speech = f"Reminder set for {time_str}: {title}"
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "reminder_id": reminder_id,
                "trigger_time": trigger_time_utc.isoformat(),
                "trigger_time_local": trigger_time_local.isoformat(),
                "formatted_time": time_str,
                "recurring": recurrence_rule is not None,
                "recurrence_rule": recurrence_rule
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to create reminder: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()

