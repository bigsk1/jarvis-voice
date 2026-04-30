#!/usr/bin/env python3
"""
List Reminders Tool
Query reminders by status and time range.

Input: {
    "status": "current|scheduled|triggered|acknowledged|all",  # optional, default "current"
    "limit": 10  # optional, default 10
}

Output: {
    "ok": bool,
    "speech": str,
    "data": {
        "reminders": [...]
    }
}
"""

import sys
import os
import json
import sqlite3
from datetime import datetime, timezone

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value
from memory_db import MemoryDB
from time_utils import get_app_timezone, parse_utc_timestamp, to_local_from_utc_string

def format_time_relative(trigger_time_str: str) -> str:
    """Format trigger time as relative time (e.g., 'in 2 hours', '5 minutes ago')."""
    try:
        trigger_time = parse_utc_timestamp(trigger_time_str)
        now = datetime.now(timezone.utc)
        delta = trigger_time - now
        
        if delta.total_seconds() < 0:
            # Past
            seconds = abs(delta.total_seconds())
            if seconds < 60:
                return "just now"
            elif seconds < 3600:
                mins = int(seconds / 60)
                return f"{mins} minute{'s' if mins != 1 else ''} ago"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
            else:
                days = int(seconds / 86400)
                return f"{days} day{'s' if days != 1 else ''} ago"
        else:
            # Future
            seconds = delta.total_seconds()
            if seconds < 60:
                return "in less than a minute"
            elif seconds < 3600:
                mins = int(seconds / 60)
                return f"in {mins} minute{'s' if mins != 1 else ''}"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"in {hours} hour{'s' if hours != 1 else ''}"
            else:
                days = int(seconds / 86400)
                return f"in {days} day{'s' if days != 1 else ''}"
    except:
        return trigger_time_str


def format_trigger_time_local(trigger_time_str: str, tz) -> str:
    """Convert UTC trigger_time to a human-readable local time string."""
    try:
        local_time = to_local_from_utc_string(trigger_time_str, tz)
        return local_time.strftime('%A, %B %d, %Y at %I:%M %p %Z')
    except:
        return trigger_time_str


def sort_current_reminders(reminders: list[dict]) -> list[dict]:
    """Prioritize triggered reminders first, then scheduled by nearest time."""
    def sort_key(reminder: dict):
        status_priority = 0 if reminder.get('status') == 'triggered' else 1
        try:
            trigger_time = parse_utc_timestamp(reminder['trigger_time'])
        except Exception:
            trigger_time = datetime.max.replace(tzinfo=timezone.utc)
        return (status_priority, trigger_time)

    return sorted(reminders, key=sort_key)


def sort_all_reminders(reminders: list[dict]) -> list[dict]:
    """Keep live reminders first, then recent history."""
    def safe_time(value: str | None, fallback_future: bool = False):
        if not value:
            return datetime.max.replace(tzinfo=timezone.utc) if fallback_future else datetime.min.replace(tzinfo=timezone.utc)
        try:
            return parse_utc_timestamp(value)
        except Exception:
            return datetime.max.replace(tzinfo=timezone.utc) if fallback_future else datetime.min.replace(tzinfo=timezone.utc)

    def sort_key(reminder: dict):
        status = reminder.get('status')
        if status == 'triggered':
            return (0, safe_time(reminder.get('trigger_time'), fallback_future=True))
        if status == 'scheduled':
            return (1, safe_time(reminder.get('trigger_time'), fallback_future=True))
        if status == 'acknowledged':
            return (2, -safe_time(reminder.get('acknowledged_at')).timestamp())
        if status == 'canceled':
            return (3, -safe_time(reminder.get('trigger_time')).timestamp())
        if status == 'expired':
            return (4, -safe_time(reminder.get('trigger_time')).timestamp())
        return (5, -safe_time(reminder.get('trigger_time')).timestamp())

    return sorted(reminders, key=sort_key)


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
        status_filter = args.get('status', 'current').lower()
        limit = args.get('limit', 10)
        
        # Valid statuses
        valid_statuses = ['current', 'scheduled', 'triggered', 'acknowledged', 'all']
        if status_filter not in valid_statuses:
            raise ValueError(f"status must be one of: {', '.join(valid_statuses)}")
        
        # Query database
        db = MemoryDB()
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build query
        if status_filter == 'current':
            query = """
                SELECT * FROM reminders
                WHERE status IN ('scheduled', 'triggered')
                ORDER BY
                    CASE WHEN status = 'triggered' THEN 0 ELSE 1 END,
                    trigger_time ASC
                LIMIT ?
            """
            params = (limit,)
        elif status_filter == 'all':
            query = """
                SELECT * FROM reminders
                ORDER BY
                    CASE
                        WHEN status = 'triggered' THEN 0
                        WHEN status = 'scheduled' THEN 1
                        WHEN status = 'acknowledged' THEN 2
                        ELSE 3
                    END,
                    trigger_time ASC
                LIMIT ?
            """
            params = (limit,)
        else:
            query = """
                SELECT * FROM reminders
                WHERE status = ?
                ORDER BY trigger_time ASC
                LIMIT ?
            """
            params = (status_filter, limit)
        
        rows = cursor.execute(query, params).fetchall()
        conn.close()
        
        # Get local timezone for display
        local_tz = get_app_timezone(get_config_value("JARVIS_TIMEZONE", "America/Los_Angeles"))
        
        # Format reminders
        reminders = []
        for row in rows:
            reminder = dict(row)
            reminder['relative_time'] = format_time_relative(reminder['trigger_time'])
            reminder['trigger_time_local'] = format_trigger_time_local(reminder['trigger_time'], local_tz)
            reminders.append(reminder)
        
        if status_filter == 'current':
            reminders = sort_current_reminders(reminders)
        elif status_filter == 'all':
            reminders = sort_all_reminders(reminders)
        else:
            reminders.sort(key=lambda r: parse_utc_timestamp(r['trigger_time']))
        
        # Generate speech
        if not reminders:
            speech = "You have no current reminders." if status_filter == 'current' else "You have no reminders"
            if status_filter not in ('all', 'current'):
                speech += f" with status '{status_filter}'"
            speech += "."
        else:
            count = len(reminders)
            
            # Group by status for summary
            scheduled = [r for r in reminders if r['status'] == 'scheduled']
            triggered = [r for r in reminders if r['status'] == 'triggered']
            triggered_spoken = [r for r in triggered if bool(r.get('spoken'))]
            triggered_unspoken = [r for r in triggered if not bool(r.get('spoken'))]
            
            if status_filter in ('current', 'all'):
                # Highlight triggered (missed) reminders first
                if triggered:
                    if len(triggered) == 1:
                        t = triggered[0]
                        spoken_note = " It already played out loud." if t.get('spoken') else " It has not been spoken yet."
                        speech = f"Yes, you have 1 triggered reminder: '{t['title']}' from {t['relative_time']}.{spoken_note} "
                    else:
                        speech = f"Yes, you have {len(triggered)} triggered reminders"
                        if triggered_spoken and triggered_unspoken:
                            speech += f", {len(triggered_spoken)} already spoken and {len(triggered_unspoken)} not yet spoken"
                        elif triggered_spoken:
                            speech += f", all {len(triggered_spoken)} already spoken"
                        elif triggered_unspoken:
                            speech += f", none spoken yet"
                        speech += ". "
                        speech += f"Most urgent: '{triggered[0]['title']}' from {triggered[0]['relative_time']}. "
                    
                    # Add scheduled info if any
                    if scheduled:
                        next_scheduled = scheduled[0]
                        speech += f"You also have {len(scheduled)} upcoming reminder{'s' if len(scheduled) != 1 else ''}. "
                        speech += f"Next: '{next_scheduled['title']}' {next_scheduled['relative_time']}."
                else:
                    # No triggered, just scheduled
                    if scheduled:
                        speech = f"You have {len(scheduled)} upcoming reminder{'s' if len(scheduled) != 1 else ''}. "
                        next_reminder = scheduled[0]
                        speech += f"Next: '{next_reminder['title']}' {next_reminder['relative_time']}."
                    else:
                        if status_filter == 'all':
                            historical = [r for r in reminders if r['status'] not in ('scheduled', 'triggered')]
                            historical_count = len(historical)
                            acknowledged_count = sum(1 for r in historical if r['status'] == 'acknowledged')
                            if historical_count > 0:
                                if acknowledged_count == historical_count:
                                    speech = f"You have no current reminders. The most recent results are {historical_count} acknowledged reminder{'s' if historical_count != 1 else ''}."
                                else:
                                    speech = f"You have no current reminders. I found {historical_count} past reminder{'s' if historical_count != 1 else ''}, including {acknowledged_count} acknowledged."
                            else:
                                speech = "You have no current reminders."
                        else:
                            speech = "You have no current reminders."
            else:
                # Specific status filter
                if status_filter == 'triggered':
                    # User specifically asked for triggered/missed reminders
                    if count == 1:
                        r = reminders[0]
                        spoken_note = " It already played out loud." if r.get('spoken') else " It has not been spoken yet."
                        speech = f"You have 1 triggered reminder: '{r['title']}' from {r['relative_time']}.{spoken_note}"
                    else:
                        speech = f"You have {count} triggered reminders"
                        if triggered_spoken and triggered_unspoken:
                            speech += f", {len(triggered_spoken)} already spoken and {len(triggered_unspoken)} not yet spoken"
                        elif triggered_spoken:
                            speech += f", all {len(triggered_spoken)} already spoken"
                        elif triggered_unspoken:
                            speech += f", none spoken yet"
                        speech += ". "
                        speech += f"Most urgent: '{reminders[0]['title']}' from {reminders[0]['relative_time']}."
                else:
                    speech = f"Found {count} {status_filter} reminder{'s' if count != 1 else ''}"
                    if count > 0:
                        first = reminders[0]
                        speech += f". First: '{first['title']}' {first['relative_time']}."
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "reminders": reminders,
                "count": len(reminders)
            }
        }))
        
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to list reminders: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
