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
import requests
from datetime import datetime, timedelta, timezone

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB
from time_utils import (
    add_days_local,
    add_months_local,
    ensure_local,
    format_utc_db,
    format_utc_z,
    get_app_timezone,
    now_local,
    now_utc,
    replace_day_safe,
)


def sync_to_google_calendar(reminder_id: int, title: str, description: str, 
                            trigger_time_utc: datetime, recurrence_rule: str = None) -> dict:
    """Sync reminder to Google Calendar via n8n webhook.
    
    Args:
        reminder_id: Jarvis reminder ID
        title: Reminder title
        description: Reminder description
        trigger_time_utc: Trigger time in UTC
        recurrence_rule: Optional recurrence rule (WEEKLY:2, MONTHLY:10)
        
    Returns:
        dict with gcal_event_id if successful, None otherwise
    """
    webhook_url = get_config_value('N8N_JARVIS_WEBHOOK_URL')
    
    if not webhook_url:
        # n8n sync not configured, skip silently
        return None
    
    try:
        # Format time as ISO 8601 with Z suffix to indicate UTC
        # This ensures n8n/Google Calendar interprets the time correctly
        trigger_time_iso = format_utc_z(trigger_time_utc)
        
        payload = {
            "action": "create",
            "reminder": {
                "id": reminder_id,
                "title": title,
                "description": description or "",
                "trigger_time": trigger_time_iso,
                "recurrence_rule": recurrence_rule
            }
        }
        
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10
        )
        
        if response.ok:
            result = response.json()
            return result
        else:
            # Log error but don't fail the reminder creation
            print(f"Warning: Google Calendar sync failed: {response.status_code}", file=sys.stderr)
            return None
            
    except Exception as e:
        # Log error but don't fail the reminder creation
        print(f"Warning: Google Calendar sync error: {e}", file=sys.stderr)
        return None

def word_to_number(word: str) -> int:
    """Convert word numbers to integers."""
    word_map = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
        'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
        'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60,
        'a': 1, 'an': 1
    }
    return word_map.get(word.lower(), None)

def normalize_time_words(text: str) -> str:
    """Convert word numbers in time expressions to digits.
    
    Examples:
    - "in one hour" -> "in 1 hour"
    - "in thirty minutes" -> "in 30 minutes"
    - "in two days" -> "in 2 days"
    """
    # Pattern: word + time unit
    pattern = r'\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|' \
              r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|' \
              r'thirty|forty|fifty|sixty|a|an)\s+(minute|min|hour|hr|day|week)s?\b'
    
    def replace_word(match):
        word = match.group(1)
        unit = match.group(2)
        number = word_to_number(word)
        if number:
            return f"{number} {unit}"
        return match.group(0)
    
    return re.sub(pattern, replace_word, text, flags=re.IGNORECASE)


def normalize_meridiem(text: str) -> str:
    """Normalize meridiem variants like 'p.m.' and 'a m' to 'pm'/'am'."""
    if not text:
        return text
    normalized = text.lower()
    # Handle dotted and spaced forms: p.m., p m, p.m, etc.
    normalized = re.sub(r'\b([ap])\s*\.?\s*m\.?\b', r'\1m', normalized)
    return normalized

def parse_multi_day_pattern(when: str):
    """Parse patterns that require multiple individual reminders.
    
    Patterns:
    - "next 5 days at 2pm"
    - "for the next 5 days at 2pm"
    - "5 days in a row at 2pm"
    - "every day for 5 days at 2pm"
    
    Returns: (num_days, time_match) or (None, None) if not a multi-day pattern
    """
    when_lower = when.lower()
    
    # Pattern: "next N days" or "for the next N days"
    next_days_match = re.search(r'(?:for\s+)?(?:the\s+)?next\s+(\d+)\s+days?', when_lower)
    if next_days_match:
        num_days = int(next_days_match.group(1))
        return num_days, when_lower
    
    # Pattern: "N days in a row"
    in_a_row_match = re.search(r'(\d+)\s+days?\s+in\s+a\s+row', when_lower)
    if in_a_row_match:
        num_days = int(in_a_row_match.group(1))
        return num_days, when_lower
    
    # Pattern: "every day for N days" or "every day for the next N days"
    every_day_match = re.search(r'every\s+day\s+(?:for\s+)?(?:the\s+)?(?:next\s+)?(\d+)\s+days?', when_lower)
    if every_day_match:
        num_days = int(every_day_match.group(1))
        return num_days, when_lower
    
    return None, None


def parse_recurrence(when: str):
    """Parse recurring patterns from time expression.
    
    Returns: recurrence_rule string or None
    - "DAILY" for every day
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
        
        # Check for "every day" (infinite daily - no bounded limit)
        # Must NOT have a day limit like "for 5 days"
        if when_lower.startswith('day') and not re.search(r'for\s+(?:the\s+)?(?:next\s+)?\d+\s+days?', when.lower()):
            return "DAILY"
    
    return None


def extract_time_from_expression(when: str, default_hour: int = 10):
    """Extract hour and minute from a time expression.
    
    Returns: (hour, minute) tuple
    """
    when = normalize_meridiem(when)
    time_match = re.search(r'(\d+)(?::(\d+))?\s*(am|pm)\b', when)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        meridiem = time_match.group(3)
        
        if meridiem == 'pm' and hour != 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
        
        return hour, minute
    
    # Check for "noon" or "midday"
    if "noon" in when.lower() or "midday" in when.lower():
        return 12, 0
    
    # Check for "midnight"
    if "midnight" in when.lower():
        return 0, 0
    
    return default_hour, 0


def parse_time_expression(when: str, default_hour: int = 10):
    """Parse natural time expressions into datetime.
    
    Args:
        when: Natural language time expression
        default_hour: Default hour to use when time not specified (default 10am)
    
    Returns:
        tuple: (trigger_datetime OR list of datetimes, recurrence_rule or None)
    
    Examples:
    - "in 30 minutes" -> (datetime, None)
    - "every wednesday" -> (next Wed 10am, "WEEKLY:2")
    - "every month on the 10th" -> (next 10th 10am, "MONTHLY:10")
    - "every day at 2pm" -> (tomorrow 2pm, "DAILY")
    - "tomorrow at 3pm" -> (datetime, None)
    - "next 5 days at 2pm" -> ([datetime1, datetime2, ...], None)  # Multiple!
    """
    when = normalize_meridiem(when).strip()
    
    # Normalize word numbers to digits (e.g., "one hour" -> "1 hour")
    when = normalize_time_words(when)
    tz = get_app_timezone()
    now = now_local()
    
    # Check for multi-day patterns FIRST (creates multiple reminders)
    num_days, _ = parse_multi_day_pattern(when)
    if num_days and num_days > 0:
        hour, minute = extract_time_from_expression(when, default_hour)
        
        # Create list of datetimes for each day
        datetimes = []
        for day_offset in range(1, num_days + 1):  # Start from tomorrow
            target = add_days_local(now, day_offset)
            target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
            datetimes.append(target)
        
        return datetimes, None  # Returns LIST, not single datetime
    
    # Check for recurring patterns
    recurrence = parse_recurrence(when)
    
    # If recurring, calculate first trigger time
    if recurrence:
        rule = recurrence
        
        # Handle DAILY recurrence (every day at X time)
        if rule == "DAILY":
            hour, minute = extract_time_from_expression(when, default_hour)
            
            # First trigger is tomorrow at the specified time
            trigger_time = add_days_local(now, 1)
            trigger_time = trigger_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            return trigger_time, rule
        
        if rule.startswith("WEEKLY:"):
            target_weekday = int(rule.split(':')[1])
            days_ahead = (target_weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week if today
            
            trigger_time = add_days_local(now, days_ahead)
            
            # Extract time from expression if provided, else use default
            time_match = re.search(r'(\d+)(?::(\d+))?\s*(am|pm)\b', when)
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
            trigger_time = replace_day_safe(trigger_time, target_day)
            if trigger_time <= now:
                # Next month, preserving the intended wall-clock time.
                trigger_time = replace_day_safe(add_months_local(trigger_time, 1), target_day)
            
            # Extract time if provided
            time_match = re.search(r'(\d+)(?::(\d+))?\s*(am|pm)\b', when)
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
        tomorrow = add_days_local(now, 1)
        
        # Check for "noon" or "midday"
        if "noon" in when or "midday" in when:
            return tomorrow.replace(hour=12, minute=0, second=0, microsecond=0), None
        
        # Check for "midnight"
        if "midnight" in when:
            return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0), None
        
        # Check for specific time
        time_match = re.search(r'(\d+)\s*(am|pm)\b', when)
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
    time_match = re.search(r'(\d+)(?::(\d+))?\s*(am|pm)\b', when)
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
            target = add_days_local(target, 1)
        
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
    return dt.strftime("%A, %B %d at %I:%M %p %Z")


def create_single_reminder(title: str, description: str, trigger_time_local: datetime, 
                           recurrence_rule: str = None, db_path: str = None):
    """Create a single reminder in the database and sync to Google Calendar.
    
    Returns: dict with reminder details
    """
    import sqlite3
    
    # Convert to UTC for storage using the configured local timezone.
    trigger_time_local = ensure_local(trigger_time_local, get_app_timezone())
    trigger_time_utc = trigger_time_local.astimezone(timezone.utc)
    
    conn = sqlite3.connect(db_path)
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
        format_utc_db(trigger_time_utc),
        now_utc().isoformat(),
        recurrence_rule
    ))
    
    reminder_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # Sync to Google Calendar via n8n
    gcal_result = sync_to_google_calendar(
        reminder_id=reminder_id,
        title=title,
        description=description,
        trigger_time_utc=trigger_time_utc,
        recurrence_rule=recurrence_rule
    )
    
    # If sync succeeded, update reminder metadata
    gcal_synced = False
    gcal_event_id = None
    if gcal_result and gcal_result.get('ok'):
        gcal_event_id = gcal_result.get('gcal_event_id')
        if gcal_event_id:
            gcal_synced = True
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            metadata = json.dumps({
                "gcal_event_id": gcal_event_id,
                "gcal_synced": True,
                "gcal_synced_at": now_utc().isoformat()
            })
            cursor.execute("UPDATE reminders SET metadata = ? WHERE id = ?", (metadata, reminder_id))
            conn.commit()
            conn.close()
    
    return {
        "reminder_id": reminder_id,
        "trigger_time": format_utc_db(trigger_time_utc),
        "trigger_time_local": trigger_time_local.isoformat(),
        "formatted_time": format_local_time(trigger_time_local),
        "recurring": recurrence_rule is not None,
        "recurrence_rule": recurrence_rule,
        "gcal_synced": gcal_synced,
        # Note: gcal_event_id intentionally excluded from response to prevent
        # LLM from speaking the long ID. It's stored in the database for sync purposes.
    }


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
        
        # Parse time (returns tuple: datetime OR list of datetimes, recurrence_rule)
        trigger_result, recurrence_rule = parse_time_expression(when)
        
        # Get database path
        db = MemoryDB()
        db_path = db.db_path
        
        # Check if we have multiple datetimes (multi-day pattern)
        if isinstance(trigger_result, list):
            # Create multiple individual reminders
            reminders_created = []
            gcal_synced_count = 0
            
            for trigger_time_local in trigger_result:
                result = create_single_reminder(
                    title=title,
                    description=description,
                    trigger_time_local=trigger_time_local,
                    recurrence_rule=None,  # Individual reminders, not recurring
                    db_path=db_path
                )
                reminders_created.append(result)
                if result.get('gcal_synced'):
                    gcal_synced_count += 1
            
            # Format response for multiple reminders
            num_reminders = len(reminders_created)
            first_date = reminders_created[0]['formatted_time']
            last_date = reminders_created[-1]['formatted_time']
            
            speech = f"Created {num_reminders} reminders for '{title}': {first_date} through {last_date}"
            if gcal_synced_count > 0:
                speech += f". All {gcal_synced_count} added to Google Calendar."
            
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {
                    "reminders_created": num_reminders,
                    "reminders": reminders_created,
                    "first_reminder": reminders_created[0],
                    "last_reminder": reminders_created[-1],
                    "gcal_synced_count": gcal_synced_count
                }
            }))
        else:
            # Single reminder (original behavior)
            trigger_time_local = trigger_result
            
            result = create_single_reminder(
                title=title,
                description=description,
                trigger_time_local=trigger_time_local,
                recurrence_rule=recurrence_rule,
                db_path=db_path
            )
            
            # Format response
            if recurrence_rule:
                speech = f"Recurring reminder set: {title}. First trigger {result['formatted_time']}"
            else:
                speech = f"Reminder set for {result['formatted_time']}: {title}"
            
            if result.get('gcal_synced'):
                speech += ". Also added to Google Calendar."
            
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": result
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
